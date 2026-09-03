"""背景式上下文翻译冒烟测试：
1. storage.recent_context：取前 N 句（seq 升序）、跳过识别/翻译失败行
2. translate.build_context_user：prompt 结构（背景行 + 当前句行，不翻译背景）
3. recorder final_worker：真实链路 —— 定稿新句时从 DB 取前 2 句注入 tsl.translate
"""
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DEEPSEEK_API_KEY"] = "sk-test-dummy"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = ROOT / "scripts" / "_smoke_ctx_tmp"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "audio").mkdir(parents=True, exist_ok=True)

from app import config, recorder as rec_mod
from app.storage import Store
from app import translate as tsl_mod

config.AUDIO_DIR = TMP / "audio"
config.DB_PATH = TMP / "subtitle.db"
# 固定背景窗口 = 2 句（与生产默认一致）
config.TRANSLATE_CONTEXT = 2


class FakeSrc:
    def __init__(self, sample_rate, wav_out): pass
    def start(self): pass
    def read(self): return None
    def stop(self): pass


class FakeEngine:
    def __init__(self, sr, partial_win, asr_win, partial_asr_win=None,
                 ring_sec=None, on_partial=None, on_final=None):
        self.ring = []
        self.asr_win = asr_win
        self.sr = sr
    def feed(self, block, fed): pass
    def ring_rms(self): return 0.0
    def finalize(self, fed, from_t=None): pass
    def reset(self): pass


rec_mod.AudioSource = FakeSrc
rec_mod.StreamingEngine = FakeEngine


class FakeTr:
    def transcribe(self, audio, beam=1, vad=False): return "okay, moving on."


class FakeTslCtx:
    """记录每次 translate 收到的 (en, context)，返回假译文。"""
    def __init__(self):
        self.calls = []
    def translate(self, en, context=None):
        self.calls.append((en, context))
        return f"[zh] {en}"


store = Store(TMP / "subtitle.db")

# ---- 1. storage.recent_context ----
sid = store.create_session(course_id=None, title="背景测试")
store.add_segment(sid, 1, 100.0, 105.0, "first sentence.", "第一句。")
store.add_segment(sid, 2, 106.0, 111.0, "second sentence.", "第二句。")
store.add_segment(sid, 3, 112.0, 117.0, "[ASR错误] boom", "（未识别到清晰语音）")
store.add_segment(sid, 4, 118.0, 123.0, "fourth sentence.", "[翻译失败] timeout")

# before_seq=5 应拿到最近 2 句：seq 3(ASR失败)、4(翻译失败) 都被跳过 → seq 1、2 升序
ctx = store.recent_context(sid, 5, n=2)
assert ctx == [("first sentence.", "第一句。"), ("second sentence.", "第二句。")], f"recent_context 错误: {ctx}"
# before_seq=3 → 只取 seq<3（seq 1、2 两条），升序
ctx2 = store.recent_context(sid, 3, n=2)
assert ctx2 == [("first sentence.", "第一句。"), ("second sentence.", "第二句。")], f"before_seq 边界错误: {ctx2}"
# before_seq=2 → 只剩 seq 1
assert store.recent_context(sid, 2, n=2) == [("first sentence.", "第一句。")]
# n=0（关闭背景）→ 空列表
assert store.recent_context(sid, 5, n=0) == []
print("[OK] storage.recent_context: 前 N 句升序、跳过失败行、n=0 关闭")

# ---- 2. translate.build_context_user ----
user = tsl_mod.build_context_user("Current sentence.", [("first sentence.", "第一句。"), ("second sentence.", "第二句。")])
assert "背景1（英文）：first sentence." in user
assert "背景1（中文）：第一句。" in user
assert "背景2（中文）：第二句。" in user
assert user.strip().endswith("请翻译当前句：Current sentence."), f"末尾应为当前句: {user!r}"
assert "第一句。" in user
# 空 context → 旧格式
assert tsl_mod.build_context_user("Hi.", None) == "请翻译：Hi."
assert tsl_mod.build_context_user("Hi.", []) == "请翻译：Hi."
print("[OK] translate.build_context_user: 背景行 + 当前句行")

# LLM 引擎 context 生效时用 CONTEXT_SYSTEM_PROMPT（不真的发请求，仅验调用路径）
class ProbeTsl(tsl_mod.DeepSeekTranslator):
    def __init__(self):
        super().__init__(api_key="sk-x", model="probe")
        self.seen = []
    def _call(self, system, user, max_tokens=512):
        self.seen.append((system, user))
        return "译文"

p = ProbeTsl()
p.translate("hello.", context=[("a.", "甲。")])
sys_, user_ = p.seen[0]
assert sys_ == tsl_mod.CONTEXT_SYSTEM_PROMPT, "有 context 应走背景系统提示词"
assert "请翻译当前句：hello." in user_
assert p.last_zh == "译文", "context 分支也应更新 last_zh"
p.translate("no context here.")   # 无 context → 旧 SYSTEM_PROMPT + 上一句译文
assert p.seen[1][0] == tsl_mod.SYSTEM_PROMPT
assert "上一句译文（上下文）：译文" in p.seen[1][1]
print("[OK] translate.DeepSeek: context 分支用背景提示词，无 context 保持旧行为")

# ---- 3. recorder final_worker 真实注入链路 ----
# 直接启动 worker 线程（不走麦克风），往 f_q 塞一条定稿句，验证传进
# tsl.translate 的 context 恰好是前 2 句（seq 2、4 的英中，跳过失败行）
sid2 = store.create_session(course_id=None, title="注入链路")
store.add_segment(sid2, 1, 1.0, 2.0, "ctx sentence one.", "背景句一。")
store.add_segment(sid2, 2, 3.0, 4.0, "ctx sentence two.", "背景句二。")

fake_tsl = FakeTslCtx()
rec = rec_mod.Recorder(store, FakeTr(), fake_tsl)
rec.session_id = sid2
rec._reset_state()
rec._start_workers()
rec.f_q.put((sid2, 3, 5.0, 6.0, "current sentence here."))

def wait_segment(timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if store.count_segments(sid2) == 3:
            return True
        time.sleep(0.02)
    return False

assert wait_segment(), "final_worker 未把新句入库"
assert len(fake_tsl.calls) == 1, f"translate 应只被调 1 次，实际 {len(fake_tsl.calls)}"
en, ctx = fake_tsl.calls[0]
assert en == "current sentence here.", f"当前句传错: {en!r}"
assert ctx == [("ctx sentence one.", "背景句一。"), ("ctx sentence two.", "背景句二。")], f"背景传错: {ctx}"
row = store.get_session(sid2)  # 触发一次查询，确认库内 zh
seg = store.conn.execute("SELECT translated_text FROM segments WHERE session_id=? AND seq=3", (sid2,)).fetchone()
assert seg[0] == "[zh] current sentence here.", f"入库译文错误: {seg[0]}"
print("[OK] recorder.final_worker: 新句翻译携带前 2 句英中背景，逐句对齐入库")

# 收尾：停 worker 线程（哨兵与生产一致：元组形式，不能裸放 None）
rec.asr_q.put((9, 999, None))
for _ in range(3):
    time.sleep(0.05)
    if not any(t.is_alive() for t in rec._workers):
        break

shutil.rmtree(TMP, ignore_errors=True)
print("\n=== 上下文感知翻译冒烟测试全部通过 ===")
