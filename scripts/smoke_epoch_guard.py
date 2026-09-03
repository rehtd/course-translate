"""P0 修复验证：停止→续录/新建的 worker 代际隔离（2026-09-02）。

覆盖：
1. final_worker 拦截跨会话任务：f_q 里 sid 不匹配当前会话的任务
   不放回死循环、不写入本课节（放回超限丢弃）
2. 代际机制：stop 收尾后立即 start 新会话，旧代际 worker 退出，
   新会话句子只写入新课节，不串到旧课节
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

TMP = ROOT / "scripts" / "_smoke_epoch_tmp"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "audio").mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication([])

from app import config, recorder as rec_mod
from app.storage import Store

config.AUDIO_DIR = TMP / "audio"
config.DB_PATH = TMP / "subtitle.db"


class FakeSrc:
    def __init__(self, sample_rate, wav_out):
        self._out = Path(wav_out)
    def start(self):
        self._out.parent.mkdir(parents=True, exist_ok=True)
        self._out.write_bytes(b"RIFFfake")
    def read(self):
        return None
    def stop(self):
        pass


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
    def transcribe(self, audio, beam=1, vad=False): return "hello world."


class FakeTsl:
    def translate(self, en, context=None): return "你好，世界。"


store = Store(TMP / "subtitle.db")


def wait_done(sid, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if store.get_session(sid)[5] == "done":
            return True
        time.sleep(0.05)
    return False


def wait_segments(sid, n, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if store.count_segments(sid) >= n:
            return True
        time.sleep(0.02)
    return False


def texts(sid):
    return [r[0] for r in store.conn.execute(
        "SELECT raw_text FROM segments WHERE session_id=? ORDER BY seq", (sid,)).fetchall()]


rec = rec_mod.Recorder(store, FakeTr(), FakeTsl())

# ---- 1. 会话 A 启动 ----
rec.start(course_id=None, title="会话 A")
sid_a = rec.session_id
# 等 worker 就绪（_start_workers 已同步完成，线程已启动）
time.sleep(0.3)

# 正确归属的任务：sid_a → 入库
rec.f_q.put((sid_a, 1, 1.0, 2.0, "own sentence A."))
assert wait_segments(sid_a, 1), "sid_a 任务未入库"
assert texts(sid_a) == ["own sentence A."], texts(sid_a)

# 跨会话任务：sid=999 ≠ sid_a → 拦截，不写入 sid_a（放回 3 次后丢弃）
rec.f_q.put((999, 2, 3.0, 4.0, "foreign sentence."))
time.sleep(2.0)   # 等放回/丢弃流程走完（0.5s get 轮询 × 3 次 + 余量）
assert texts(sid_a) == ["own sentence A."], f"跨会话任务污染了 sid_a: {texts(sid_a)}"
assert store.count_segments(999) == 0, "伪造 sid 不应有数据"
print("[OK] final_worker 拦截跨会话任务：不写入错误课节、无死循环")

# ---- 2. 停止 A → 立即新建 B（代际切换）----
rec.stop()
assert wait_done(sid_a), "会话 A 结束卡住"
old_alive = [t for t in rec._workers if t.is_alive()]
rec.start(course_id=None, title="会话 B")
sid_b = rec.session_id
assert sid_b != sid_a, "新会话应有新 sid"
time.sleep(1.0)   # 等旧代际 worker 检测到 epoch 退出
assert not any(t.is_alive() for t in old_alive), "旧代际 worker 未在 epoch 后退出"

# 新会话句子只进 sid_b
rec.f_q.put((sid_b, 1, 5.0, 6.0, "own sentence B."))
assert wait_segments(sid_b, 1), "sid_b 任务未入库"
assert texts(sid_b) == ["own sentence B."], texts(sid_b)
# 旧课节 A 不受影响
assert texts(sid_a) == ["own sentence A."], f"sid_a 被串改: {texts(sid_a)}"
print(f"[OK] 代际切换：A={texts(sid_a)} B={texts(sid_b)} 互不串台")

# 残留代际的脏任务（旧 sid）在新代际中被拦截，不写入 B
rec.f_q.put((sid_a, 3, 7.0, 8.0, "stale from A era."))
time.sleep(2.0)
assert texts(sid_b) == ["own sentence B."], f"残留旧代际任务污染 B: {texts(sid_b)}"
assert texts(sid_a) == ["own sentence A."], f"sid_a 不应新增: {texts(sid_a)}"
print("[OK] 残留旧代际任务在新代际中被拦截（不写 B、不重复写 A）")

rec.stop()
assert wait_done(sid_b), "会话 B 结束卡住"

# 收尾：确保 worker 退出
rec._epoch_ev.set()
for t in rec._workers:
    t.join(timeout=2)

shutil.rmtree(TMP, ignore_errors=True)
print("\n=== P0 代际隔离冒烟测试全部通过 ===")
QTimer.singleShot(0, app.quit)
app.processEvents()
