"""续录（继续录制到已结束课节）冒烟测试：
1. storage：resume_session / add_session_audio / list_session_audio / max_seq
2. Recorder.continue_session 状态机：done→recording→(stop)→done，seq 接着编号，
   续录 wav 登记 cont1/cont2，可反复续录
3. UI：btn_continue 存在且选中已结束课节后可用；_build_audio_routes 多 wav 排序
"""
import os
import shutil
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DEEPSEEK_API_KEY"] = "sk-test-dummy"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = ROOT / "scripts" / "_smoke_continue_tmp"
shutil.rmtree(TMP, ignore_errors=True)
(TMP / "audio").mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication([])

from app import config, recorder as rec_mod
from app.storage import Store

# 测试环境指向临时目录，避免污染真实 data/
config.AUDIO_DIR = TMP / "audio"
config.DB_PATH = TMP / "subtitle.db"


class FakeSrc:
    def __init__(self, sample_rate, wav_out):
        self._out = Path(wav_out)
    def start(self):
        self._out.parent.mkdir(parents=True, exist_ok=True)
        self._out.write_bytes(b"RIFFfake")   # 占位，仅验证存在性与路径
    def read(self):
        return None   # 立即结束 feed_loop
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

# ---- 1. storage ----
sid = store.create_session(course_id=None, title="第 1 节")
for i in range(3):
    store.add_segment(sid, i + 1, 100.0 + i, 105.0 + i, f"seg {i+1}", f"译 {i+1}")
store.end_session(sid)
assert store.get_session(sid)[5] == "done", "初始应为 done"
assert store.max_seq(sid) == 3, f"max_seq 应为 3，实际 {store.max_seq(sid)}"

store.resume_session(sid)
s = store.get_session(sid)
assert s[5] == "recording" and s[4] is None, "resume 后应 recording 且 ended_at 清空"
print("[OK] storage: resume_session / max_seq")

# ---- 2. Recorder.continue_session 状态机 ----
# 无头环境下非 Qt 线程发信号到纯 Python callable 不一定即时投递，
# 以轮询 DB 状态为准（生产环境连 QObject 槽走事件循环，正常）
def wait_done(timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if store.get_session(sid)[5] == "done":
            return True
        time.sleep(0.05)
    return False

rec = rec_mod.Recorder(store, FakeTr(), FakeTsl())
rec.continue_session(sid)
s = store.get_session(sid)
assert s[5] == "recording", "续录后应 recording"
rows = store.list_session_audio(sid)
assert len(rows) == 1 and rows[0][1] == f"session_{sid}_cont1.wav", f"续录登记错误: {rows}"
assert rec.session_id == sid
assert rec.seq[0] == 3, f"seq 应从 3 接着编号，实际 {rec.seq[0]}"
assert (config.AUDIO_DIR / f"session_{sid}_cont1.wav").exists(), "续录 wav 未创建"
print("[OK] recorder.continue_session: 状态回 recording、seq=3、cont1.wav 已登记")

rec.stop()
assert wait_done(), "结束续录后未回到 done（收尾卡住）"
print("[OK] recorder.stop: 结束续录回到 done")

# 反复续录 → cont2
rec.continue_session(sid)
rows = store.list_session_audio(sid)
assert len(rows) == 2 and rows[1][1] == f"session_{sid}_cont2.wav", f"二次续录登记错误: {rows}"
assert rec.seq[0] == 3
rec.stop()
assert wait_done(), "二次续录结束未回到 done"
print("[OK] 二次续录: cont2.wav 登记、序号继续")

# ---- 3. UI：按钮 + 路由 ----
from app.ui.main_window import MainWindow
win = MainWindow(store)
win._model_ready = True          # 跳过模型预热等待
assert hasattr(win, "btn_continue"), "缺少 btn_continue"
assert not win.btn_continue.isEnabled(), "未选中课节时继续按钮应禁用"

# 主录音 wav 造一个假的，验证路由排序
(config.AUDIO_DIR / f"session_{sid}.wav").write_bytes(b"RIFFmain")

# 测试会话是 orphan（course_id=None）→ 切到「未分类」工作区再看列表
last_item = win.course_list.item(win.course_list.count() - 1)
win._on_course_click(last_item)
assert win.session_list.count() > 0, "课节列表应为空? 至少 1 条"
item = win.session_list.item(0)
win._on_session_click(item)
assert win.btn_continue.isEnabled(), "选中已结束课节后继续按钮应可用"

routes = win._build_audio_routes(sid)
assert len(routes) == 3, f"路由应为 3 段（主+cont1+cont2），实际 {len(routes)}"
paths = [Path(r[0]).name for r in routes]
assert paths[0] == f"session_{sid}.wav", f"主录音应在最前: {paths}"
assert paths[1:] == [f"session_{sid}_cont1.wav", f"session_{sid}_cont2.wav"], f"续录顺序: {paths}"
print(f"[OK] UI: btn_continue 可用性 + 路由 {paths}")

win.close()
shutil.rmtree(TMP, ignore_errors=True)
print("\n=== 续录功能冒烟测试全部通过 ===")
QTimer.singleShot(0, app.quit)
app.processEvents()
