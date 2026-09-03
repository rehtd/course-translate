"""主窗口冒烟：构建 MainWindow + 核心控件 + 设置对话框（offscreen）。

运行: QT_QPA_PLATFORM=offscreen <venv>/bin/python tests/test_mainwindow_smoke.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.storage import Store  # noqa: E402
from app.ui.main_window import (  # noqa: E402
    MainWindow, _SettingsDialog, _NotePreviewDialog, _ASR_MODES,
    _GlossaryExtractDialog,
)

app = QApplication.instance() or QApplication([])


def test_main_window_builds():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "smoke.db")
        w = MainWindow(store, warmup=False)
        assert w.windowTitle()
        # 核心控件存在
        for attr in ("course_list", "session_list", "btn_settings",
                     "btn_new_session", "status"):
            assert hasattr(w, attr), f"missing {attr}"
        # 课程列表有 5 门课（+未分类灰显）
        count = w.course_list.count()
        assert count >= 5, f"course list items: {count}"
        # 设置对话框：ASR 模式下拉存在且默认实时
        s = {"vault": "", "notes_subdir": "01-章节笔记",
             "translate_provider": "deepseek", "asr_mode": "realtime"}
        dlg = _SettingsDialog(w, s)
        assert dlg.asr_combo.currentData() == "realtime"
        idx = dlg.asr_combo.findData("precise")
        dlg.asr_combo.setCurrentIndex(idx)
        assert dlg.values()["asr_mode"] == "precise"
        assert dlg.values()["concepts_subdir"] == "02-概念卡片"
        w.close()
        print("PASS test_main_window_builds")


def test_asr_modes_constant():
    assert set(_ASR_MODES) == {"realtime", "precise"}
    print("PASS test_asr_modes_constant")


def test_settings_lock_provider_while_recording():
    """录制中打开设置，翻译引擎下拉框必须禁用（防切引擎置空 recorder）。"""
    s = {"vault": "", "notes_subdir": "01-章节笔记",
         "translate_provider": "deepseek", "asr_mode": "realtime"}
    dlg_locked = _SettingsDialog(None, s, lock_provider=True)
    assert not dlg_locked.provider_combo.isEnabled(), "录制中 provider 应禁用"
    assert dlg_locked.values()["translate_provider"] == "deepseek"
    dlg_free = _SettingsDialog(None, s, lock_provider=False)
    assert dlg_free.provider_combo.isEnabled(), "非录制 provider 应可用"
    print("PASS test_settings_lock_provider_while_recording")


def test_app_active_does_not_hide_main_window():
    """录制中切回前台不得 hide 主窗口（旧 Dock 速览把 Cmd+Tab 当成点 Dock）。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "smoke.db")
        w = MainWindow(store, warmup=False)
        w._recording_active = True
        w.show()
        app.processEvents()
        w._on_app_state(Qt.ApplicationActive)
        app.processEvents()
        assert w.isVisible(), "切回前台主窗口应保持可见"
        # 再激活一次：旧逻辑会 hide → activateWindow → 再 hide，像卡死
        w._on_app_state(Qt.ApplicationActive)
        app.processEvents()
        assert w.isVisible(), "连续激活不得把主窗口藏掉"
        w.close()
        print("PASS test_app_active_does_not_hide_main_window")


def test_note_preview_dialog_lists_cards():
    dlg = _NotePreviewDialog(None, "# 第3节 · 梯度下降\n", [
        {"action": "新建", "name": "梯度下降", "en": "Gradient Descent",
         "one_liner": "沿梯度下山"},
        {"action": "合并", "name": "学习率", "en": "", "one_liner": ""},
    ])
    assert "梯度下降" in dlg.editor.toPlainText()
    assert dlg.result_markdown().startswith("# 第3节")
    print("PASS test_note_preview_dialog_lists_cards")


def test_load_session_bulk_no_clock_label():
    """历史课节一次性装载：回看一句一块（上英下中），不建富卡片。"""
    import time as _t
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "smoke.db")
        sid = store.create_session("t")
        t0 = 1_000_000.0
        n = 300
        for i in range(n):
            store.add_segment(sid, i + 1, t0 + i, t0 + i + 2, f"en {i}", f"中 {i}")
        w = MainWindow(store, warmup=False)
        w.show()
        app.processEvents()
        started = _t.perf_counter()
        w._load_session(sid)
        app.processEvents()
        elapsed = _t.perf_counter() - started
        assert elapsed < 1.5, f"load_session {n} 段耗时 {elapsed:.2f}s"
        assert w._workspace == "review"
        assert w.right_split.isHidden()
        assert not w.transcript.isHidden()
        assert w.transcript.count() == n
        item = w.transcript.item(0)
        assert w.transcript.itemWidget(item) is None
        data = item.data(Qt.UserRole)
        assert data["kind"] == "seg"
        assert data["zh"] == "中 0"
        assert data["en"] == "en 0"
        assert data["t0"] == t0
        assert item.text() == "en 0\n中 0"
        assert w.zh_box.toPlainText() == ""
        assert w.en_box.toPlainText() == ""
        w.close()
        print(f"PASS test_load_session_bulk_no_clock_label ({elapsed:.2f}s)")


def test_workspace_record_vs_review():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "smoke.db")
        w = MainWindow(store, warmup=False)
        assert w._workspace == "review"
        assert w.right_split.isHidden()
        assert not w.transcript.isHidden()
        w._apply_workspace("record")
        assert w._workspace == "record"
        assert w.transcript.isHidden()
        assert not w.right_split.isHidden()
        w._apply_workspace("review")
        assert w.right_split.isHidden()
        cid = w._cur_course_id
        w._recording_active = True
        w._on_course_click(w.course_list.item(1))
        assert w._cur_course_id == cid, "录制中不得切换课程"
        w.close()
        print("PASS test_workspace_record_vs_review")


def test_fill_record_boxes_then_append():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "smoke.db")
        sid = store.create_session("t")
        store.add_segment(sid, 1, 1.0, 2.0, "old en", "旧中")
        w = MainWindow(store, warmup=False)
        w._fill_record_boxes(sid)
        assert "old en" in w.en_box.toPlainText()
        assert "旧中" in w.zh_box.toPlainText()
        w._on_seg(2, 3.0, 4.0, "new en", "新中")
        assert "new en" in w.en_box.toPlainText()
        assert "新中" in w.zh_box.toPlainText()
        w.close()
        print("PASS test_fill_record_boxes_then_append")


def test_audio_routes_follow_m4a():
    """压缩后主录音只剩 m4a 时，回听路由仍能找到文件。"""
    from app import config
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        audio = tmp / "audio"
        audio.mkdir()
        store = Store(tmp / "smoke.db")
        sid = store.create_session("t")
        store.end_session(sid)
        (audio / f"session_{sid}.m4a").write_bytes(b"fake-m4a")
        old = config.AUDIO_DIR
        config.AUDIO_DIR = audio
        try:
            w = MainWindow(store, warmup=False)
            routes = w._build_audio_routes(sid)
            assert len(routes) == 1, routes
            assert Path(routes[0][0]).name == f"session_{sid}.m4a"
            w.close()
        finally:
            config.AUDIO_DIR = old
        print("PASS test_audio_routes_follow_m4a")


def test_glossary_extract_dialog_selection():
    dlg = _GlossaryExtractDialog(None, [
        {"en": "Johns Hopkins", "zh": "约翰·霍普金斯", "reason": "学校",
         "action": "新建", "old_zh": ""},
        {"en": "chart", "zh": "图", "reason": "",
         "action": "改译", "old_zh": "图表"},
    ], skipped=1)
    assert dlg.list.count() == 2
    assert dlg.list.item(0).checkState() == Qt.Checked
    assert dlg.list.item(1).checkState() == Qt.Unchecked
    assert dlg.selected_terms() == [("Johns Hopkins", "约翰·霍普金斯")]
    dlg.list.item(1).setCheckState(Qt.Checked)
    assert ("chart", "图") in dlg.selected_terms()
    print("PASS test_glossary_extract_dialog_selection")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            fails += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
