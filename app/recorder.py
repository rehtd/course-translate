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
from app.translate import asr_initial_prompt, translate_with_retry

_END_PUNCT = ".?!。？！"
_PARTIAL_STALE_SEC = 2.0    # 预翻任务入队超过此时长未处理则丢弃（新的马上会来）
_REUSE_OVERLAP = 0.5        # 定稿复用预翻的最小窗口重叠率（v3.5：partial 短窗 3s
                            # 与 final 5s 窗最大重叠 3/5=0.6，故 0.7→0.5 恢复复用）
_REUSE_STABLE = 2           # 预翻连续同文的稳定次数
_PENDING_MAX = 10.0         # 句子未完时周期定稿最多等几秒（v3.6 防腰斩兜底，
                            # 超过则强制定稿，防长句无限跳过导致内容丢失）
# 队列优先级：final 定稿(0) 必须优先于 partial 预翻(1)。
# 教训（2026-09-01 session 93）：原设计 partial=0 永远插队，精准模式下 ASR
# 变慢（~2s/个）时 asr_worker 永远在处理 partial，final 被饿死积压 209 个，
# 停止时逐个转写（7 分钟）用户强杀进程 → end_session 未执行、状态卡 recording、
# 后 18 分钟内容全部丢失。final 是入库定稿（内容），partial 只是实时预览
# （丢弃后 1.5s 内新的马上来，最多字幕跳一帧）→ final 优先，partial 靠过期丢弃兜底。
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
    """v3.6 周期定稿跳过判定：句子未完（无终止标点 且 仍在说话）且未超等待上限。

    周期定稿（每 5s）在句子中间截断会丢句子尾部词（session_99 实测 45% 段
    无终止标点结尾）。句子未完且老师还在说 → 跳过本次定稿，等句子说完
    （静音/标点）再整句入库。超 _PENDING_MAX 强制定稿兜底（防长句无限跳过）。
    """
    if since >= _PENDING_MAX:
        return False
    if not text or text[-1] in _END_PUNCT:
        return False
    # 仍在说话：能量高 或 最近 2s 内有非空文本（外放/远场低音量时 rms 偏低）
    return rms > 0.01 or talk_gap < 2.0


def _same_sentence(a: str, b: str, win_overlap: float) -> bool:
    """a 是否为 b 的同句重发（防重复定稿）。

    ASR 滑动窗口在句子定稿后会继续把同一句作为 partial 重发 2~3 次。
    v3.5 判据（短窗双轨后前缀判定失效——短窗 partial 只重发句尾片段，
    前缀重合低）：
    1. 时间窗不重叠（win_overlap ≤ 0.7）→ 新句子，放行；
    2. 长度明显增长（>+2 字符）→ 残句补全（周期定稿截走半句后拿到完整句），
       必须放行；
    3. 同音频且长度不增 → 检查 a 是否大部分被 b 覆盖（同句重发/尾部片段），
       覆盖率高则判同句跳过。
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
        self.tr_final = tr_final   # v3.7 双轨：定稿精修模型（如 medium）；None 则复用 tr
        self.asr_mode = asr_mode
        # 模式参数：start() 时按 asr_mode 计算（见 _apply_mode），录制中修改属性下次录制生效
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
        self.m_q: "queue.Queue" = queue.Queue()    # 定稿精修通道（v3.7：final 音频 → medium）
        self.p_q: "queue.Queue" = queue.Queue()    # partial 实时字幕通道（独立线程）
        self.f_q: "queue.Queue" = queue.Queue()    # final 定稿入库通道（独立线程）
        self.ui_q: "queue.Queue" = queue.Queue()   # partial 决策通道
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
        """按 asr_mode 计算识别参数：realtime=5s 窗+beam1 预翻、无 VAD（现状）；
        precise=10s 窗+beam3 预翻、VAD 滤环境音（更准更稳，延迟约 +0.5s）。

        产品分层：字幕要快、框内要准。
        v3.5 流畅度优化（仅 realtime 生效，precise 保持原参数不动）：
        - partial_win 1.5→1.2s（字幕触发更频繁）
        - partial_asr_win 3.0s 短窗（只喂悬浮字幕）
        - 定稿按 [上一句切点, 现在] 整段精修，写入右侧框（可慢）
        """
        """按 asr_mode 计算识别参数。

        字幕路径（partial）始终短窗 + greedy：上课跟读要快。
        框内路径（final）受 asr_mode 影响：realtime 默认 5s 起切；
        precise 把定稿窗口拉到 10s 并在精修时开 VAD，字幕不跟着变慢。
        """
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
        # 关键：正常结束路径必须停掉采集源（此前只停在错误路径）——否则
        # sounddevice 流一直开着、wav 持续写入直到应用退出：会话音频里
        # 混入结束后的声音、队列无限增长（内存泄漏）。
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
        self._asr_put(9, None)   # 哨兵（最高优先级序号，最后处理）
        # 正常收尾：残留的 final 翻译通常每个 <1s，10s 足够；若翻译引擎卡死/超时
        # （如网络异常 15s 超时 × 多句积压），也不阻塞保存——worker 是 daemon 线程，
        # 超时后直接 end_session，剩余句子的翻译结果随后异步补入（store 有锁，安全）。
        # 并行 join（而非串行 3×10s）：最快让 UI 收到 idle，避免用户以为卡死而强杀进程
        # （强杀 → end_session 永远不执行 → DB 卡 recording，2026-09-01 session 93 教训）。
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
        # 代际机制（P0 修复 2026-09-02）：终止上一代 worker。
        # 停止收尾 join 超时后，残留 worker（daemon）仍可能活着并消费队列；
        # 若此时用户立即「继续录制/新建」，旧 worker 会把新会话句子写进旧课节
        # （闭包 sid 是旧的）或重复入库。每代持独立 Event：新代启动时 set 旧代的，
        # 旧 worker 在 get(timeout=0.5) 轮询里检测到即退出，不再消费新任务。
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
        # 延迟埋点：asr=识别耗时，ptr=预翻翻译耗时，ftr=定稿翻译耗时，reuse=定稿复用预翻次数
        stats = {"asr_p": [], "asr_f": [], "ptr": [], "ftr": [], "reuse": 0, "drop": 0}
        _stats_lock = threading.Lock()

        def _report(force=False):
            with _stats_lock:
                n = len(stats["asr_p"]) + len(stats["asr_f"])
                if not force and n % 30 != 0:
                    return
                def _f(v):
                    return f"{sum(v)/len(v)*1000:.0f}ms" if v else "-"
                print(f"[perf] ASR预翻 {_f(stats['asr_p'])} | ASR定稿 {_f(stats['asr_f'])} | "
                      f"预翻翻译 {_f(stats['ptr'])} | 定稿翻译 {_f(stats['ftr'])} | "
                      f"复用 {stats['reuse']} | 丢弃过期partial {stats['drop']}", flush=True)
                for k in ("asr_p", "asr_f", "ptr", "ftr"):
                    stats[k] = stats[k][-10:]

        def asr_worker():
            # 预翻稳定性跟踪（供定稿复用判定——仅单模型模式用）
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
                    # 单模型模式（tr_final=None，兼容旧行为）：复用预翻或 small beam5
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
                        _dbg("asr_worker：定稿复用预翻文本")
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
            """v3.7 定稿精修通道：独立线程 + 独立模型实例逐句精修。

            字幕草稿（small）与框内精修并行：字幕跟读不被定稿拖住。
            不与草稿共用 _mlock（不同实例线程安全）。"""
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
            """实时字幕通道：独立线程，final 定稿翻译再慢也不阻塞 partial 上屏。

            v3（2026-09-01 用户拍板）：不再做 partial 预翻——用户不追求翻译速度，
            中文译文统一由 final 定稿翻译后累积到主窗口「中文译文区」。
            partial 只负责把英文识别结果快速上屏（省一半 API 调用：每 1.5s 一次
            的预翻彻底取消；句子定稿后只翻译一次）。
            """
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
                        # 背景式上下文翻译：当前句单独翻译，前 N 句英中对照作背景
                        # 注入 prompt（帮指代/话题理解，维持逐句 1:1 对齐；0=关闭）
                        ctx = store.recent_context(sid, s, n=config.TRANSLATE_CONTEXT)
                        zh = translate_with_retry(tsl, en, context=ctx or None)
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

    def _on_partial(self, audio, t0, t1):
        with self._plock:
            if self._partial_pending[0]:
                return
            self._partial_pending[0] = True
        _dbg(f"on_partial t0={t0:.1f} t1={t1:.1f}（入 asr_q 预翻）")
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
                        # v3.6 防腰斩丢尾词：5s 周期定稿在句子中间截断时，
                        # 句子后半（最后几个词）会丢（session_99 实测 45% 段
                        # 无终止标点结尾）。若最近转写无终止标点（句子未完）
                        # 且仍在说话（能量高）且未超等待上限 → 跳过本次定稿，
                        # 等句子说完（静音 rms 低 → 能量条件不满足 → 正常定稿，
                        # 或标点定稿先触发）再整句入库。
                        _rms = engine.ring_rms()
                        _since = fed_sec - last_final_t[0]
                        # 未完 = 最近转写无终止标点 且 仍在说话（能量高 或 最近 2s
                        # 内有非空文本——外放/远场低音量时 rms 偏低，用 talk 兜底）
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
                            # 同句重发去重：定稿后 ASR 滑动窗口还会把同一句重发
                            # 2~3 次。v3.5 判据 = 时间窗重叠 + 长度不增 + 文本覆盖
                            # （短窗 partial 只重发句尾片段，前缀重合低 → 前缀判据
                            # 失效）；残句补全（周期定稿截走半个句子后拿到完整句，
                            # 长度明显增长）必须放行。
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
