"""功能走查 + 关闭后残留（offscreen，不打开真麦克风、不打网）。

覆盖：课程/课节/搜索/导出/全文/术语/设置/悬浮窗/暂停态/关窗清理。
实时识别与云翻译不在这里跑。

运行: QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/test_feature_lifecycle.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleFactory  # noqa: E402

from app.overlay import ControlChip, SubtitleBar, make_floating  # noqa: E402
from app.storage import Store  # noqa: E402
from app.ui.main_window import (  # noqa: E402
    MainWindow, _APP_QSS, _SettingsDialog, _TranscriptDialog,
    _open_obsidian_note,
)

app = QApplication.instance() or QApplication([])


def _store(tmp: str) -> Store:
    return Store(Path(tmp) / "life.db")


def test_fonts_include_windows_fallbacks():
    assert "Microsoft YaHei" in _APP_QSS
    assert "Segoe UI" in _APP_QSS
    from app.ui import main_window as mw
    src = Path(mw.__file__).read_text(encoding="utf-8")
    assert "Consolas" in src
    print("PASS test_fonts_include_windows_fallbacks")


def test_course_session_search_export_glossary():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = _store(tmp)
        w = MainWindow(store, warmup=False)
        n0 = w.course_list.count()
        cid = store.add_course("TST001", "Lifecycle Course")
        w._reload_course_list()
        assert w.course_list.count() == n0 + 1
        store.rename_course(cid, "TST001", "Renamed Course")
        w._reload_course_list()
        labels = [w.course_list.item(i).text() for i in range(w.course_list.count())]
        assert any("Renamed Course" in t for t in labels)

        sid = store.create_session("第 1 节", course_id=cid)
        store.add_segment(sid, 1, 1.0, 2.0, "gradient descent", "梯度下降")
        store.add_segment(sid, 2, 3.0, 4.0, "learning rate", "学习率")
        store.end_session(sid)
        n_stale = store.create_session("残留", course_id=cid)
        store.conn.execute("UPDATE sessions SET status='recording' WHERE id=?", (n_stale,))
        store.conn.commit()
        assert store.recover_stale_sessions() >= 1
        assert store.get_session(n_stale)[5] == "done"

        w._cur_course_id = cid
        w._reload_session_list()
        assert w.session_list.count() >= 1
        w._load_session(sid)
        assert w.transcript.count() == 2
        w._apply_filter("梯度")
        hidden = sum(1 for i in range(w.transcript.count())
                     if w.transcript.item(i).isHidden())
        assert hidden == 1
        w._apply_filter("")
        assert all(not w.transcript.item(i).isHidden()
                   for i in range(w.transcript.count()))

        out = Path(tmp) / "export.md"
        path = store.export_markdown(sid, path=str(out), title="第 1 节")
        text = Path(path).read_text(encoding="utf-8")
        assert "gradient descent" in text and "梯度下降" in text

        store.upsert_glossary_terms(cid, [("gradient descent", "梯度下降")])
        assert ("gradient descent", "梯度下降") in store.list_glossary(cid)

        dlg = _TranscriptDialog(w)
        dlg.load_session(sid)
        assert dlg.list.count() == 2
        dlg.lang_combo.setCurrentIndex(1)  # 中文
        app.processEvents()
        blob = " ".join(dlg.list.item(i).text() for i in range(dlg.list.count()))
        assert "梯度下降" in blob
        dlg.close()

        store.delete_course(cid)
        w._reload_course_list()
        labels = [w.course_list.item(i).text() for i in range(w.course_list.count())]
        assert not any("Renamed Course" in t for t in labels)
        w.close()
    print("PASS test_course_session_search_export_glossary")


def test_settings_and_light_combo():
    s = {"vault": r"E:\vault", "notes_subdir": "01-章节笔记",
         "concepts_subdir": "02-概念卡片",
         "translate_provider": "deepseek", "asr_mode": "realtime",
         "input_device": ""}
    dlg = _SettingsDialog(None, s)
    vals = dlg.values()
    assert vals["vault"] == r"E:\vault"
    assert vals["asr_mode"] == "realtime"
    assert "input_device" in vals
    fusion = QStyleFactory.create("Fusion")
    assert dlg.mic_combo.style().objectName() == fusion.objectName()
    assert dlg.provider_combo.style().objectName() == fusion.objectName()
    dlg.close()
    print("PASS test_settings_and_light_combo")


def test_overlay_pause_and_clickthrough():
    bar = SubtitleBar()
    chip = ControlChip()
    assert bar.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert not chip.testAttribute(Qt.WA_TransparentForMouseEvents)
    bar.show()
    chip.show()
    app.processEvents()
    make_floating(bar)
    make_floating(chip)
    if sys.platform == "win32":
        assert not bar.testAttribute(Qt.WA_MacAlwaysShowToolWindow)
        assert not chip.testAttribute(Qt.WA_MacAlwaysShowToolWindow)
        assert getattr(bar, "_float_timer", None) is None
        assert bar.en.font().family() != "Helvetica Neue"
    bar.show_paused(True)
    app.processEvents()
    assert "PAUSE" in (bar._raw_en or bar.en.text() or "")
    chip.set_paused(True)
    assert "PAUSE" in chip.status.text()
    bar.close()
    chip.close()
    app.processEvents()
    print("PASS test_overlay_pause_and_clickthrough")


def test_open_obsidian_note_windows_path():
    if sys.platform != "win32":
        print("SKIP test_open_obsidian_note_windows_path")
        return
    called = []

    def fake_startfile(url):
        called.append(url)

    with patch("os.startfile", fake_startfile):
        _open_obsidian_note(Path(r"E:\vault\01-章节笔记\课.md"))
    assert called and called[0].startswith("obsidian://open?path=")
    print("PASS test_open_obsidian_note_windows_path")


def test_close_clears_overlay_timers_and_threads():
    before = {id(t) for t in threading.enumerate()}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        w = MainWindow(_store(tmp), warmup=False)
        w._show_overlay()
        w.show()
        app.processEvents()
        assert w.bar is not None and w.chip is not None
        w.btn_new_session.setEnabled(True)
        w.close()
        app.processEvents()
        time.sleep(0.15)
        assert w.bar is None and w.chip is None
        visible = [x for x in QApplication.allWidgets()
                   if x.isVisible() and x.__class__.__name__ in ("SubtitleBar", "ControlChip")]
        assert visible == [], visible
        leftover = [
            t.name for t in threading.enumerate()
            if id(t) not in before and t.is_alive()
            and t.name in ("win-mic-request",)  # 我们自己起的
        ]
        assert leftover == [], leftover
    print("PASS test_close_clears_overlay_timers_and_threads")


def test_record_workspace_locks_and_fake_pause():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = _store(tmp)
        w = MainWindow(store, warmup=False)
        cid = w._cur_course_id
        w._model_ready = True
        w._apply_workspace("record")
        w._on_state("recording")
        assert w.btn_new_session.isEnabled() is False
        assert w.btn_pause.isEnabled() is True
        assert w.btn_stop.isEnabled() is True
        w._on_course_click(w.course_list.item(1))
        assert w._cur_course_id == cid
        w._on_state("paused")
        assert "继续" in w.btn_pause.text()
        w._on_state("idle")
        assert w.btn_new_session.isEnabled() is True
        w.close()
    print("PASS test_record_workspace_locks_and_fake_pause")


def test_subprocess_exits_without_orphan():
    """子进程关窗后必须退出，不能留下 python 孤儿。"""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    env["QT_SCALE_FACTOR"] = "1"
    env["CT_LIFECYCLE_CHILD"] = "1"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        cwd=str(ROOT), env=env, timeout=45,
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
    assert proc.returncode == 0, proc.stderr
    print("PASS test_subprocess_exits_without_orphan")


def _child_main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication as QA
    from app.storage import Store as St
    from app.ui.main_window import MainWindow as MW
    qa = QA.instance() or QA([])
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        w = MW(St(Path(tmp) / "c.db"), warmup=False)
        w._show_overlay()
        w.show()
        qa.processEvents()
        w.close()
        qa.processEvents()
        time.sleep(0.2)
        alive = [
            t.name for t in threading.enumerate()
            if t.is_alive() and t.name == "win-mic-request"
        ]
        vis = [x.__class__.__name__ for x in QA.allWidgets()
               if x.isVisible() and x.__class__.__name__ in ("SubtitleBar", "ControlChip")]
        if alive or vis:
            sys.stderr.write(f"leftover threads={alive} widgets={vis}\n")
            return 1
    return 0


if os.environ.get("CT_LIFECYCLE_CHILD") == "1":
    raise SystemExit(_child_main())


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
        except Exception:  # noqa: BLE001
            fails += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
