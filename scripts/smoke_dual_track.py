"""v3.7 双轨识别冒烟测试：草稿 small（快速跟读）+ 定稿 medium（准确入库）。

验证：
1. final 任务分流到精修通道（tr_final），入库文本是精修模型结果
2. 单模型模式（tr_final=None）兼容旧路径（small beam5 定稿）
3. 停收尾哨兵链正常（m_q → f_q 退出链路）
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

TMP = ROOT / "scripts" / "_smoke_dual_tmp"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "audio").mkdir(parents=True, exist_ok=True)

import numpy as np  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from app import config, recorder as rec_mod  # noqa: E402
from app.storage import Store  # noqa: E402

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


class FakeTrSmall:
    """草稿模型（small）：只服务 partial。"""
    def transcribe(self, audio, beam=1, vad=False): return "PARTIAL-SMALL"


class FakeTrMedium:
    """精修模型（medium）：只服务 final。"""
    def transcribe(self, audio, beam=1, vad=False): return "FINAL-MEDIUM-POLISHED"


class FakeTsl:
    def translate(self, en, context=None): return f"[zh]{en}"


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


# ---- 1. 双轨：final 走 medium 精修 ----
rec = rec_mod.Recorder(store, FakeTrSmall(), FakeTsl(), tr_final=FakeTrMedium())
rec.start(course_id=None, title="双轨会话")
sid = rec.session_id
time.sleep(0.3)   # 等 worker 就绪

audio5 = np.zeros(16000 * 5, dtype=np.float32)
rec._on_final(audio5, 0.0, 5.0)   # 模拟一次定稿（5s 窗）
assert wait_segments(sid, 1), "final 未入库"
raw = store.conn.execute(
    "SELECT raw_text, translated_text FROM segments WHERE session_id=? AND seq=1",
    (sid,)).fetchone()
assert raw[0] == "FINAL-MEDIUM-POLISHED", f"入库文本应为 medium 精修结果: {raw[0]!r}"
assert raw[1] == "[zh]FINAL-MEDIUM-POLISHED", f"翻译应基于 medium 文本: {raw[1]!r}"
print("[OK] 双轨：final 定稿入库 = medium 精修文本 + 基于精修文本翻译")

# ---- 2. 停收尾（哨兵链 m_q→f_q 正常）----
rec.stop()
assert wait_done(sid), "双轨会话收尾卡住"
print("[OK] 双轨收尾：哨兵链正常退出")

# ---- 3. 单模型兼容（tr_final=None → small beam5 定稿入库）----
rec2 = rec_mod.Recorder(store, FakeTrSmall(), FakeTsl(), tr_final=None)
rec2.start(course_id=None, title="单模型会话")
sid2 = rec2.session_id
time.sleep(0.3)
rec2._on_final(audio5, 0.0, 5.0)
assert wait_segments(sid2, 1), "单模型 final 未入库"
raw2 = store.conn.execute(
    "SELECT raw_text FROM segments WHERE session_id=? AND seq=1", (sid2,)).fetchone()
# 单模型模式：复用预翻逻辑或 small 直接转——FakeTrSmall 返回 PARTIAL-SMALL
assert raw2[0] == "PARTIAL-SMALL", f"单模型应走 tr 转写: {raw2[0]!r}"
rec2.stop()
assert wait_done(sid2), "单模型会话收尾卡住"
print("[OK] 单模型兼容：tr_final=None 走旧路径")

shutil.rmtree(TMP, ignore_errors=True)
print("\n=== 双轨识别冒烟测试全部通过 ===")
QTimer.singleShot(0, app.quit)
app.processEvents()
