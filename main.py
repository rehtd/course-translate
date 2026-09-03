"""同传课堂 主程序。

用法:
  python main.py                        # 桌面应用
  python main.py --export <session_id>  # 导出指定 session 为 Markdown
  python main.py --agent-note <id>     # 用笔记 Agent 整理课节并写入 vault
"""
import argparse

from app import config


def run_app():
    """桌面应用模式。"""
    import sys
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.storage import Store
    from app.ui.main_window import MainWindow

    if not config.DEEPSEEK_API_KEY:
        app = QApplication([])
        QMessageBox.critical(
            None, "缺少配置",
            "未找到 DEEPSEEK_API_KEY。\n请在项目 .env 中填写（参照 .env.example）。")
        return 1

    # 运行日志落盘，便于排查问题（每次写入立即 flush，异常/崩溃也能留痕）
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _log = open(config.DATA_DIR / "app.log", "a", encoding="utf-8")

        class _LiveLog:
            def __init__(self, f):
                self._f = f

            def write(self, s):
                self._f.write(s)
                self._f.flush()

            def flush(self):
                self._f.flush()

            def __getattr__(self, name):
                return getattr(self._f, name)

        sys.stdout = _LiveLog(_log)
        sys.stderr = _LiveLog(_log)
    except Exception:  # noqa: BLE001
        pass

    store = Store()
    store.recover_stale_sessions()   # 清理上次异常退出的残留 recording，避免 UI 一直显示录音中
    app = QApplication([])
    win = MainWindow(store)
    win.show()
    return app.exec()


def main():
    ap = argparse.ArgumentParser(description="同传课堂")
    ap.add_argument("--export", type=int, default=None, metavar="SESSION_ID",
                    help="导出指定 session 为 Markdown 后退出")
    ap.add_argument("--agent-note", type=int, default=None, metavar="SESSION_ID",
                    help="用笔记 Agent 整理指定 session 并写入 vault")
    args = ap.parse_args()

    if args.agent_note is not None:
        from pathlib import Path
        from app.note_agent import NoteAgent
        from app.storage import Store
        from app.vault_notes import meta_from_settings, render_lecture, write_vault
        store = Store()
        sess = store.get_session(args.agent_note)
        if not sess:
            print(f"ERROR: session {args.agent_note} 不存在")
            return 1
        cid = sess[1]
        course = store.get_course(cid) if cid else None
        course_name = f"{course[1]} {course[2]}".strip() if course else "课堂实录"
        course_code = (course[1] or "").strip() if course else ""
        n = store.session_index(args.agent_note)
        draft = NoteAgent(store).generate_note(
            args.agent_note, course=course_name, title=sess[2] or "课堂实录")
        meta = meta_from_settings(course_code, course_name, args.agent_note, n)
        existing = store.get_note_path(args.agent_note)
        lecture_path = Path(existing) if existing else None
        if lecture_path is not None and not lecture_path.exists():
            lecture_path = None
        result = write_vault(meta, draft, lecture_path=lecture_path)
        store.set_note_path(args.agent_note, str(result.lecture_path))
        print(render_lecture(meta, draft))
        print(f"\n--- 课节页: {result.lecture_path}")
        print(f"--- 概念卡 新建 {len(result.created_concepts)} 合并 {len(result.updated_concepts)}")
        print(f"--- 概览: {result.moc_path}")
        return 0

    if args.export is not None:
        from app.storage import Store
        path = Store().export_markdown(args.export)
        print(f"已导出: {path}")
        return 0

    return run_app()


if __name__ == "__main__":
    main()
