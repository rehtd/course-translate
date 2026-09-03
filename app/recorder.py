"""后台录音控制器：封装采集/流式引擎/工作线程，通过 Qt 信号与 UI 通信。

信号全部从工作线程发出，Qt 会自动投递到 UI 线程（线程安全）。
"""
import queue
import threading
import time
from difflib import SequenceMatcher

from PySide6.QtCore import QObject, Signal

from app import config
from app.audio import AudioSource
from app.streamer import StreamingEngine
from app.translate import (asr_initial_prompt, join_en, looks_cut,
                           pending_truncated, should_stitch, translate_with_retry)

_END_PUNCT = ".?!。？！"
_PARTIAL_STALE_SEC = 2.0    # 字幕草稿入队超时未处理则丢弃
_REUSE_OVERLAP = 0.5        # 定稿复用字幕草稿的最小窗口重叠率
_REUSE_STABLE = 2           # 字幕草稿连续同文的稳定次数
_PENDING_MAX = 10.0         # 句子未完时周期定稿最多再等几秒，超时强制切
# 定稿优先于字幕草稿，避免精修排队时字幕任务把入库饿死。
_PRIO_FINAL = 0
_PRIO_PARTIAL = 1


def _dbg(msg: str):
    """带时间戳的调试日志（落 data/app.log，用于定位采集/定稿链路问题）。"""
    print(f"[{time.strftime('%H:%M:%S', time.localtime())}] {msg}", flush=True)


def _drain(q: "queue.Queue"):
    """清空队列残留（复用 Recorder 实例前调用，防旧任务污染新会话）。"""
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """两条时间窗口的重叠率 = 交集/并集。"""
    i = max(0.0, min(a1, b1) - max(a0, b0))
    u = max(a1, b1) - min(a0, b0)
    return i / u if u > 0 else 0.0


def _prefix_ratio(a: str, b: str) -> float:
    """共同前缀长度占较长文本的比例（0~1）。用于判断 partial 文本是否已稳定。"""
    if not a or not b:
        return 0.0
    m = 0
    for x, y in zip(a, b):
        if x != y:
            break
        m += 1
    return m / max(len(a), len(b))


def _sentence_incomplete(text: str, rms: float, talk_gap: float, since: float) -> bool:
    """周期定稿时：无句末标点且仍在说话则先跳过，超时则强制切。"""
    if since >= _PENDING_MAX:
        return False
    if not text or text[-1] in _END_PUNCT:
        return False
    # 仍在说话：能量高，或最近 2s 有转写（外放时 rms 可能偏低）
    return rms > 0.01 or talk_gap < 2.0


def _same_sentence(a: str, b: str, win_overlap: float) -> bool:
    """a 是否为 b 的同句重发（防重复定稿）。

    滑动窗会把刚定稿的句子再送 2～3 次。时间窗不重叠或明显变长则放行；
    同窗且大部分被旧句覆盖则跳过。
    """
    if not a or not b:
        return False
    if win_overlap <= 0.7:
        return False                    # 新音频：放行
    if len(a) > len(b) + 2:
        return False                    # 残句补全：放行
    sm = SequenceMatcher(None, a.lower(), b.lower())
    covered = sum(x.size for x in sm.get_matching_blocks()) / max(1, len(a))
    return covered > 0.8


class Recorder(QObject):
    seg_finalized = Signal(int, float, float, str, str)  # seq, t0, t1, en, zh
    seg_zh_updated = Signal(int, str)                     # 补上先前因截断而推迟的译文
    partial_ready = Signal(str, str)                     # en, zh（进行中字幕）
    marker_added = Signal(str, str, float)               # kind, note, t
    state_changed = Signal(str)                          # recording/paused/saving/idle
    session_done = Signal(int)                           # session_id

    def __init__(self, store, tr, tsl, asr_mode: str = "realtime", tr_final=None,
                 parent=None):
        super().__init__(parent)
        self.store = store
        self.tr = tr
        self.tsl = tsl
        self.tr_final = tr_final   # None = 草稿和定稿共用 self.tr
        self.asr_mode = asr_mode
        # start() 时按 asr_mode 写入；录制中改设置只影响下一场
        self._asr_win = 5.0
        self._partial_beam = 1
        self._vad = False
        self.session_id = None
        self.paused_ev = threading.Event()
        self.cmd_q: "queue.Queue[str]" = queue.Queue()
        self._stop_ev = threading.Event()
        self._feed_thread = None
        self._workers = []
        self.asr_q: "queue.PriorityQueue" = queue.PriorityQueue()  # (prio, seq, item)
        self.m_q: "queue.Queue" = queue.Queue()    # 定稿精修
        self.p_q: "queue.Queue" = queue.Queue()    # 实时字幕
        self.f_q: "queue.Queue" = queue.Queue()    # 定稿入库
        self.ui_q: "queue.Queue" = queue.Queue()   # 字幕上屏
        self._plock = threading.Lock()
        self._partial_pending = [False]
        self.seq = [0]
        self._asr_counter = [0]
        # 时间戳换算锚点：墙钟时间 = anchor_wall + (音频相对时间 - anchor_fed)
        self._anchor_wall = 0.0
        self._anchor_fed = 0.0
        self._fed_sec = 0.0
        # 最近一次 finalize 的音频时刻（周期定稿/暂停/收尾共用，防重复定稿）
        self._last_final_t = [0.0]
        # 最近一次定稿的文本快照（稳定标点定稿的去重基准：防 ASR 同句重发）
        self._last_final_text = [""]
        # 最近一次定稿覆盖的窗口 [t0, t1]（调试/一致性用；去重主判据是 _last_final_text）
        self._last_final_win = [0.0, 0.0]
        self._asr_hint = ""

    # ---------- 对外控制（UI 线程调用） ----------
    def _apply_mode(self):
        """字幕始终短窗 greedy；precise 只加长框内定稿窗口并开 VAD。"""
        precise = self.asr_mode == "precise"
        self._asr_win = 10.0 if precise else 5.0
        self._partial_beam = 1
        self._vad = precise
        self._partial_win = 1.2
        self._partial_asr_win = 3.0

    def start(self, course_id: int | None = None, title: str = "课堂实录"):
        self._apply_mode()
        self._apply_glossary(course_id)
        self.session_id = self.store.create_session(course_id=course_id, title=title)
        self._reset_state()
        try:
            self._launch(f"session_{self.session_id}.wav")
        except Exception:
            self.store.abort_session(self.session_id)
            raise

    def continue_session(self, sid: int):
        """续录：把已结束的课节重新打开，新内容追加到同一节。

        同一 session_id，seq 接着编号；音频写新 wav（session_{sid}_contN.wav，
        不动原文件），起始墙钟登记进 session_audio 供回听路由。
        结束流程与普通录制相同（stop → end_session）。
        """
        self._apply_mode()
        self.session_id = sid
        sess = self.store.get_session(sid)
        self._apply_glossary(sess[1] if sess else None)
        self.store.resume_session(sid)
        self._reset_state()
        rows = self.store.list_session_audio(sid)
        ord_ = len(rows) + 1
        wav_name = f"session_{sid}_cont{ord_}.wav"
        start_epoch = time.time()
        try:
            self._launch(wav_name)
        except Exception:
            # 续录失败：恢复课节到「已结束」状态，不残留 recording
            self.store.end_session(sid)
            raise
        self.store.add_session_audio(sid, ord_, wav_name, start_epoch)

    def _reset_state(self):
        """重置全部会话状态（GUI 复用同一 Recorder 实例 → 每次录制必须重来，
        否则第二次录制会残留第一次的值（如 _last_final_t 残留会让周期定稿
        fed-last≥5s 永不满足 → 有字幕但不入库）。"""
        self._last_final_t[0] = 0.0
        self._last_final_text[0] = ""
        self._last_final_win[:] = [0.0, 0.0]
        self.seq[0] = self.store.max_seq(self.session_id)
        self._asr_counter[0] = 0
        self._partial_pending[0] = False
        for q in (self.asr_q, self.m_q, self.p_q, self.f_q, self.ui_q):
            _drain(q)

    def _apply_glossary(self, course_id: int | None):
        terms = self.store.list_glossary(course_id) if course_id else []
        if hasattr(self.tsl, "set_glossary"):
            self.tsl.set_glossary(terms)
        self._asr_hint = asr_initial_prompt(terms)

    def _asr_kw(self) -> dict:
        return {"initial_prompt": self._asr_hint} if self._asr_hint else {}

    def _launch(self, wav_name: str):
        """公共启动尾段：起 worker、开麦；失败时清理 wav 并抛异常。"""
        config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        wav_out = config.AUDIO_DIR / wav_name
        self.paused_ev.clear()
        self._stop_ev.clear()
        self._anchor_wall = time.time()
        self._anchor_fed = 0.0
        self._start_workers()
        self.src = AudioSource(sample_rate=config.SAMPLE_RATE, wav_out=str(wav_out))
        self.engine = StreamingEngine(
            sr=config.SAMPLE_RATE, partial_win=self._partial_win,
            asr_win=self._asr_win, partial_asr_win=self._partial_asr_win,
            # 定稿可能等句子说完（最多 _PENDING_MAX），ring 必须能装下整段
            ring_sec=max(self._asr_win + 4.0, _PENDING_MAX + 2.0),
            on_partial=self._on_partial, on_final=self._on_final)
        try:
            self.src.start()   # 麦克风权限/设备错误在此抛出
        except Exception:
            self.src.stop()
            try:
                wav_out.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            self.state_changed.emit("idle")
            raise
        self._feed_thread = threading.Thread(target=self._feed_loop, daemon=True)
        self._feed_thread.start()
        self.state_changed.emit("recording")

    def pause(self):
        self.cmd_q.put("pause")

    def resume(self):
        self.cmd_q.put("resume")

    def toggle_pause(self):
        self.cmd_q.put("resume" if self.paused_ev.is_set() else "pause")

    def mark(self):
        self.cmd_q.put("mark")

    def stop(self):
        """请求结束（非阻塞）：后台线程完成收尾后发 session_done 信号。"""
        if self._stop_ev.is_set():
            return
        _dbg(f"stop() 请求结束 session={self.session_id}")
        self._stop_ev.set()
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        _dbg("_finish 开始：等待 feed_loop 退出…")
        if self._feed_thread is not None:
            self._feed_thread.join(timeout=300)
        # 必须停采集，否则结束后 wav 还会继续写。
        src = getattr(self, "src", None)
        if src is not None:
            try:
                src.stop()
            except Exception:  # noqa: BLE001
                pass
            self.src = None
        _dbg(f"_finish：feed_loop 已退出（ring={len(self.engine.ring) if getattr(self, 'engine', None) else '?'}）")
        # asr_q：保留未处理的 final 继续走完，丢弃 partial（仅用于实时字幕，不入库），
        # 让结束保存只处理真正要存档的句子，显著加快收尾；
        # asr_worker 收尾会向 p_q / f_q 双发哨兵，翻译 worker 随之退出
        items = []
        while True:
            try:
                item = self.asr_q.get_nowait()
            except queue.Empty:
                break
            items.append(item)
        n_final = 0
        for item in items:
            if item is None:
                continue
            _prio, _seq, payload = item
            if payload is not None and payload[0] == "final":
                n_final += 1
                self.asr_q.put(item)
        _dbg(f"_finish：清理 asr_q，保留 final {n_final} 个 / 丢弃 {len(items) - n_final} 个任务")
        self._asr_put(9, None)
        # 并行短等 worker；超时也不挡保存（daemon，结果可随后补入）。
        ts = [t for t in self._workers if t is not None and t.is_alive()]
        for t in ts:
            t.join(timeout=5)
        for t in ts:
            if t.is_alive():
                _dbg("_finish：worker 仍在处理，异步补入（不阻塞保存）")
                break
        if self.session_id is not None:
            self.store.end_session(self.session_id)
            self.session_done.emit(self.session_id)
        self.state_changed.emit("idle")

    def _asr_put(self, prio: int, payload):
        """入队字幕草稿 ASR。双轨时定稿不走这条队列（直送 m_q），避免精修拦住字幕。"""
        self._asr_counter[0] += 1
        self.asr_q.put((prio, self._asr_counter[0], payload))

    # ---------- 内部 ----------
    def _start_workers(self):
        # 开新一场前结束上一代 worker，避免旧线程把句子写进上一节。
        old_ev = getattr(self, "_epoch_ev", None)
        self._epoch_ev = threading.Event()
        if old_ev is not None:
            old_ev.set()
        # 清理已退出线程的引用，避免 _workers 无限增长
        self._workers = [t for t in self._workers if t is not None and t.is_alive()]

        tr, tsl, store = self.tr, self.tsl, self.store
        sid = self.session_id
        asr_q, m_q, p_q, f_q, ui_q = (self.asr_q, self.m_q, self.p_q,
                                      self.f_q, self.ui_q)
        plock, pending = self._plock, self._partial_pending
        # 延迟埋点：asr=识别耗时，ftr=定稿翻译耗时，reuse=定稿复用草稿次数
        stats = {"asr_p": [], "asr_f": [], "ptr": [], "ftr": [], "reuse": 0, "drop": 0}
        _stats_lock = threading.Lock()

        def _report(force=False):
            with _stats_lock:
                n = len(stats["asr_p"]) + len(stats["asr_f"])
                if not force and n % 30 != 0:
                    return
                def _f(v):
                    return f"{sum(v)/len(v)*1000:.0f}ms" if v else "-"
                print(f"[perf] ASR草稿 {_f(stats['asr_p'])} | ASR定稿 {_f(stats['asr_f'])} | "
                      f"预翻翻译 {_f(stats['ptr'])} | 定稿翻译 {_f(stats['ftr'])} | "
                      f"复用 {stats['reuse']} | 丢弃过期partial {stats['drop']}", flush=True)
                for k in ("asr_p", "asr_f", "ptr", "ftr"):
                    stats[k] = stats[k][-10:]

        def asr_worker():
            # 草稿稳定性跟踪（供定稿复用判定——仅单模型模式用）
            last_pt0, last_pt1 = [None], [None]
            last_ptext = [""]
            stable = [0]
            while True:
                if self._epoch_ev.is_set():
                    return   # 代际终止：本会话已结束，不再消费任何新任务
                try:
                    _prio, _seq, item = asr_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    break
                kind, s, t0, t1, audio = item[:5]
                if kind == "partial":
                    with plock:
                        pending[0] = False
                    # 过期丢弃：入队超时未处理说明积压，跳过（新 partial 马上来）
                    if time.time() - t1 > _PARTIAL_STALE_SEC:
                        with _stats_lock:
                            stats["drop"] += 1
                        _dbg(f"asr_worker：丢弃过期 partial（t1={t1:.1f}）")
                        continue
                    t0a = time.time()
                    try:
                        with self._mlock:
                            # 字幕草稿：关 VAD、greedy；精修走独立线程，互不抢锁
                            text = tr.transcribe(audio, beam=self._partial_beam,
                                                 vad=False, **self._asr_kw())
                    except Exception as e:  # noqa: BLE001
                        text = f"[ASR错误] {e}"
                    if self._epoch_ev.is_set():
                        return   # 推理期间已切会话：结果丢弃，不写入新队列
                    with _stats_lock:
                        stats["asr_p"].append(time.time() - t0a)
                    _dbg(f"asr_worker：字幕草稿 {time.time()-t0a:.2f}s 文本={text[:30]!r}")
                    last_pt0[0], last_pt1[0] = t0, t1
                    if (text and not text.startswith("[ASR错误]")
                            and text == last_ptext[0]):
                        stable[0] += 1
                    else:
                        last_ptext[0] = text
                        stable[0] = 1
                    p_q.put((kind, s, t0, t1, text))
                else:
                    # 兼容：若仍有 final 进 asr_q（单模型，或旧路径）
                    _sid = item[5] if len(item) > 5 else self.session_id
                    if tr_final is not None:
                        m_q.put((_sid, s, t0, t1, audio))
                        continue
                    # 单模型（tr_final=None）：复用字幕草稿或 small beam5
                    text = None
                    can_reuse = (stable[0] >= _REUSE_STABLE
                                 and last_ptext[0]
                                 and not last_ptext[0].startswith("[ASR错误]")
                                 and last_pt0[0] is not None
                                 and last_ptext[0][-1] in _END_PUNCT)
                    if can_reuse and _overlap(last_pt0[0], last_pt1[0], t0, t1) >= _REUSE_OVERLAP:
                        text = last_ptext[0]
                        with _stats_lock:
                            stats["reuse"] += 1
                        _dbg("asr_worker：定稿复用字幕草稿")
                    if text is None:
                        t0a = time.time()
                        try:
                            with self._mlock:
                                text = tr.transcribe(audio, vad=True, **self._asr_kw())   # 框内定稿：VAD+beam5
                        except Exception as e:  # noqa: BLE001
                            text = f"[ASR错误] {e}"
                        with _stats_lock:
                            stats["asr_f"].append(time.time() - t0a)
                        _dbg(f"asr_worker：定稿转写 {time.time()-t0a:.2f}s 文本={text[:30]!r}")
                    if self._epoch_ev.is_set():
                        return
                    # sid 用入队时带上的，不用 self.session_id（后者可能已切到新课节）
                    f_q.put((_sid, s, t0, t1, text))
            p_q.put(None)   # 哨兵：字幕通道退出
            if tr_final is not None:
                m_q.put(None)   # 精修通道退出（其收尾再发 f_q 哨兵）
            else:
                f_q.put(None)
            _report(force=True)

        def final_asr_worker():
            """定稿精修：独立线程和模型，不拖住字幕草稿。"""
            while True:
                if self._epoch_ev.is_set():
                    return
                try:
                    item = m_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    break
                _sid, s, t0, t1, audio = item
                t0a = time.time()
                try:
                    text = tr_final.transcribe(audio, vad=True, **self._asr_kw())   # 框内精修：VAD+beam5
                except Exception as e:  # noqa: BLE001
                    text = f"[ASR错误] {e}"
                if self._epoch_ev.is_set():
                    return
                with _stats_lock:
                    stats["asr_f"].append(time.time() - t0a)
                _dbg(f"final_asr_worker：定稿精修 {time.time()-t0a:.2f}s 文本={text[:30]!r}")
                f_q.put((_sid, s, t0, t1, text))
            f_q.put(None)   # 精修通道收尾：放行翻译入库通道退出
            _report(force=True)

        last_partial_en = [""]
        last_partial_t = [0.0]

        def partial_worker():
            """实时字幕：只上英文，不在这里翻译。"""
            while True:
                if self._epoch_ev.is_set():
                    return
                try:
                    item = p_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    break
                _, _, _, _, en = item
                if (en.startswith("[ASR错误]") or not en.strip()
                        or en == last_partial_en[0]
                        or time.time() - last_partial_t[0] < 0.15):
                    continue
                last_partial_en[0] = en
                last_partial_t[0] = time.time()
                ui_q.put((en, ""))   # 只上屏英文；中文由 final_worker 定稿后给

        def final_worker():
            while True:
                if self._epoch_ev.is_set():
                    return
                try:
                    item = f_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    break
                _sid, s, t0, t1, en = item[:5]
                if _sid != sid:
                    # 跨会话任务：放回队尾让正确代际处理；放回超限（无归属，
                    # 如对应代际已全部退出）则丢弃，避免无限放回死循环。
                    retry = item[5] if len(item) > 5 else 0
                    if retry < 3:
                        f_q.put((_sid, s, t0, t1, en, retry + 1))
                    else:
                        _dbg(f"final_worker：跨会话任务放回 {retry} 次无归属，丢弃 sid={_sid}")
                    continue
                if en.startswith("[ASR错误]") or not en.strip():
                    zh = "（未识别到清晰语音）"
                else:
                    t0t = time.time()
                    try:
                        zh = self._translate_final(store, tsl, sid, s, en)
                    except Exception as e:  # noqa: BLE001
                        zh = f"[翻译失败] {e}"
                    with _stats_lock:
                        stats["ftr"].append(time.time() - t0t)
                store.add_segment(sid, s, t0, t1, en, zh)
                self.seg_finalized.emit(s, t0, t1, en, zh)
                _dbg(f"final_worker：入库 seq={s} 文本={en[:30]!r}")
                _report()

        tr_final = self.tr_final   # 供 asr_worker/final_asr_worker 闭包引用

        self._mlock = threading.Lock()
        fns = [asr_worker, partial_worker, final_worker]
        if tr_final is not None:
            fns.insert(1, final_asr_worker)   # 双轨：medium 精修通道插在 partial 之后
        for fn in fns:
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._workers.append(t)

    def _to_wall(self, t_audio: float) -> float:
        """把音频相对时间换算成墙钟时间（含暂停重锚定）。"""
        return self._anchor_wall + (t_audio - self._anchor_fed)

    def _translate_final(self, store, tsl, sid: int, seq: int, en: str) -> str:
        """定稿翻译：截断的英文先挂起，后半段到了再拼成一句译，避免腰斩后当新句硬译。"""
        prev = store.recent_segments(sid, seq, n=5)
        chain = pending_truncated(prev)
        flushing = self._stop_ev.is_set() or self.paused_ev.is_set()
        nctx = config.TRANSLATE_CONTEXT

        if chain and not should_stitch(chain[-1][1], en):
            # 上一截不是本句后半：先把挂起的片段译掉，再译当前句
            flush_en = join_en(*(p[1] for p in chain))
            ctx = store.recent_context(sid, chain[0][0], n=nctx)
            zh_flush = translate_with_retry(tsl, flush_en, context=ctx or None)
            for pseq, _ in chain:
                store.update_segment_zh(sid, pseq, zh_flush)
            self.seg_zh_updated.emit(chain[-1][0], zh_flush)
            chain = []

        pieces = [p[1] for p in chain] + [en]
        combined = join_en(*pieces)
        still_cut = looks_cut(en)
        too_long = len(chain) >= 2 or len(combined.split()) > 80
        if still_cut and not flushing and not too_long:
            return ""

        ctx_seq = chain[0][0] if chain else seq
        ctx = store.recent_context(sid, ctx_seq, n=nctx)
        zh = translate_with_retry(tsl, combined, context=ctx or None)
        if chain and zh and not zh.startswith("[翻译失败]"):
            for pseq, _ in chain:
                store.update_segment_zh(sid, pseq, zh)
            # 不在这里发 seg_zh_updated：当前句入库后 _on_seg 会追加这一次中文
        return zh

    def _on_partial(self, audio, t0, t1):
        with self._plock:
            if self._partial_pending[0]:
                return
            self._partial_pending[0] = True
        _dbg(f"on_partial t0={t0:.1f} t1={t1:.1f}（入 asr_q 字幕草稿）")
        self._asr_put(_PRIO_PARTIAL, ("partial", 0, self._to_wall(t0), self._to_wall(t1), audio))

    def _on_final(self, audio, t0, t1):
        self.seq[0] += 1
        s = self.seq[0]
        sid = self.session_id
        wt0, wt1 = self._to_wall(t0), self._to_wall(t1)
        _dbg(f"on_final seq={s} t0={t0:.1f} t1={t1:.1f}（框内精修）")
        if self.tr_final is not None:
            # 双轨：定稿直送精修队列，不进 asr_q——字幕草稿不被精修堵住
            self.m_q.put((sid, s, wt0, wt1, audio))
        else:
            self._asr_put(_PRIO_FINAL, ("final", s, wt0, wt1, audio, sid))

    def _feed_loop(self):
        src, engine = self.src, self.engine
        last_partial = [""]   # 最新一条非空 partial 文本（标点稳定定稿的前缀比较基准）
        last_final_t = self._last_final_t   # 与 _do_pause 共用：暂停定稿也同步，防止恢复后重复定稿
        last_final_text = self._last_final_text   # 最近一次定稿文本，防同句重发
        last_final_win = self._last_final_win   # 最近一次定稿的窗口 [t0,t1]（调试/一致性用）
        last_talk = [0.0]   # 最近一次转出非空文本的 fed_sec（外放/远距低音量时替代能量判断）
        fed_sec = 0.0
        _dbg("feed_loop 启动")
        try:
            while not self._stop_ev.is_set():
                block = src.read()
                if block is None:
                    _dbg("feed_loop：read() 返回 None（音频流结束）")
                    break
                # 控制命令
                while not self.cmd_q.empty():
                    c = self.cmd_q.get_nowait()
                    if c == "pause":
                        self._do_pause()
                    elif c == "resume":
                        self._do_resume()
                    elif c == "mark":
                        self._do_mark()
                fed_sec += len(block) / config.SAMPLE_RATE
                self._fed_sec = fed_sec
                if not self.paused_ev.is_set():
                    engine.feed(block, fed_sec)
                    # 周期定稿：时间到 5s 且（能量达标 或 最近 5s 内转出过非空文本）。
                    # 外放/远距采集音量低（rms≈0.005-0.011），纯能量判断会漏掉整段句子；
                    # "最近有文本"说明 ASR 确实听到语音，比能量阈值更可靠。
                    if (fed_sec - last_final_t[0] >= engine.asr_win
                            and len(engine.ring) >= engine.asr_win * engine.sr * 0.6
                            and (engine.ring_rms() > 0.01
                                 or fed_sec - last_talk[0] < engine.asr_win + 1)):
                        # 句中不要切：无句号且还在说则跳过本次周期定稿。
                        _rms = engine.ring_rms()
                        _since = fed_sec - last_final_t[0]
                        if _sentence_incomplete(last_partial[0], _rms,
                                                fed_sec - last_talk[0], _since):
                            _dbg(f"feed_loop：句子未完，跳过周期定稿 @fed={fed_sec:.1f}"
                                 f"（已等 {_since:.0f}s，尾={last_partial[0][-15:]!r}）")
                        else:
                            span0 = last_final_t[0]
                            engine.finalize(fed_sec, from_t=span0)
                            last_final_t[0] = fed_sec
                            last_final_text[0] = last_partial[0]
                            last_final_win[:] = [span0, fed_sec]
                            _dbg(f"feed_loop：周期定稿 @fed={fed_sec:.1f} rms={_rms:.3f} "
                                 f"talk={fed_sec - last_talk[0]:.1f}s前")
                # partial 决策通道
                while not self.ui_q.empty():
                    en, zh = self.ui_q.get_nowait()
                    self.partial_ready.emit(en, zh)
                    t = en.strip()
                    if t:
                        last_talk[0] = fed_sec   # 有实际转写文本 → 记下说话时间
                        prev = last_partial[0]
                        last_partial[0] = t
                        # 稳定标点定稿：句子说完（带标点）且窗口已稳定（与上一条
                        # partial 前缀重合 >80%）。放宽"完全相同"的原因是 ASR 对
                        # 滑动窗口的输出总有抖动，严格相等几乎不出现，导致该机制
                        # 形同虚设、只能依赖 5s 周期窗口——而固定窗口会腰斩句子
                        # （"漏一句/残句"的根因）。窗口稳定=句子已说完+静音。
                        if (t[-1] in _END_PUNCT and len(t) > 12 and prev
                                and _prefix_ratio(t, prev) > 0.8
                                and len(engine.ring) >= engine.asr_win * engine.sr * 0.6):
                            # 同句重发去重：定稿后滑动窗还会把同一句再送几遍。
                            new_win = [fed_sec - engine.asr_win, fed_sec]
                            win_ov = _overlap(last_final_win[0], last_final_win[1],
                                              new_win[0], new_win[1])
                            if not _same_sentence(t, last_final_text[0], win_ov):
                                span0 = last_final_t[0]
                                engine.finalize(fed_sec, from_t=span0)
                                last_final_t[0] = fed_sec
                                last_final_text[0] = t
                                last_final_win[:] = [span0, fed_sec]
                                _dbg(f"feed_loop：稳定标点定稿 @fed={fed_sec:.1f} "
                                     f"win_ov={win_ov:.2f}")
                            last_partial[0] = ""   # 无论定稿与否都消费该句，防连续重判
                    else:
                        last_partial[0] = ""
        finally:
            _dbg(f"feed_loop 收尾：fed={fed_sec:.1f} ring={len(engine.ring)} rms={engine.ring_rms():.4f} "
                 f"stop_ev={self._stop_ev.is_set()}")
            # 收尾兜底：主循环若已在最后时刻周期定稿过（last_final_t≈fed_sec），
            # 跳过避免同一窗口重复定稿（暂停恢复后相位偏移时会发生）。
            # 但不能用 ring_rms()>0.01 判断——用户停止前若先停嘴（最后一块静音），
            # 且整段录音 < asr_win(5s) 时主循环从未 finalize，会整段 0 记录。
            if len(engine.ring) > 0 and fed_sec - last_final_t[0] >= 0.5:
                span0 = last_final_t[0]
                engine.finalize(fed_sec, from_t=span0)
                last_final_t[0] = fed_sec
                last_final_text[0] = last_partial[0]
                last_final_win[:] = [span0, fed_sec]
                _dbg(f"feed_loop 收尾：已 finalize（ring={len(engine.ring)}）")
            else:
                _dbg("feed_loop 收尾：ring 为空，跳过 finalize")
            # 哨兵统一由 _finish 在 feed join 之后发送（_asr_put(9, None)）：
            # 1) 裸 None 混入 PriorityQueue 会与 (prio, seq, item) 混合比较崩溃；
            # 2) 此处先发哨兵会被 asr_worker 立刻消费而 break，_finish 重放的
            #    final 将无人处理导致句子丢失。
            self.state_changed.emit("saving")

    # ---------- 状态操作 ----------
    def _do_pause(self):
        if self.paused_ev.is_set():
            return
        _dbg(f"暂停：ring={len(self.engine.ring)} fed={self._fed_sec:.1f}")
        # 先收尾当前句：暂停前把 ring 里未定稿的最后一段 finalize，再 reset 清空。
        # （红线语义：暂停=先收尾当前句、丢弃期间音频；若直接 reset，当前句会丢）
        if len(self.engine.ring) > 0:
            span0 = self._last_final_t[0]
            self.engine.finalize(self._fed_sec, from_t=span0)
            # 同步最近定稿时刻：否则恢复后周期定稿条件（fed - last ≥ 5s）会因
            # 相位错位立即触发，用刚清空的短 ring 定稿出幽灵段/与收尾重复定稿。
            self._last_final_t[0] = self._fed_sec
            self._last_final_win[:] = [span0, self._fed_sec]
            # 文本基准清空：暂停后 ring 重置、音频全新，旧文本无意义；
            # 置空=对恢复后第一句不做同句限制（安全方向：宁可多定，不可漏句）。
            self._last_final_text[0] = ""
        self.paused_ev.set()
        self.engine.reset()
        self.store.add_marker(self.session_id, time.time(), "pause", "⏸ 暂停")
        self.marker_added.emit("pause", "⏸ 暂停", time.time())
        self.state_changed.emit("paused")

    def _do_resume(self):
        if not self.paused_ev.is_set():
            return
        _dbg("恢复：重锚定时间戳")
        # 暂停期间墙钟在走、音频没走 → 恢复时重锚定，保证时间戳对齐真实时间
        self._anchor_wall = time.time()
        self._anchor_fed = self._fed_sec
        self.paused_ev.clear()
        self.store.add_marker(self.session_id, time.time(), "pause", "▶ 恢复")
        self.marker_added.emit("pause", "▶ 恢复", time.time())
        self.state_changed.emit("recording")

    def _do_mark(self):
        self.store.add_marker(self.session_id, time.time(), "user", "")
        self.marker_added.emit("user", "重点/疑问", time.time())
