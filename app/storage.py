"""存储：SQLite 三表（courses/sessions/segments）+ Markdown 导出。"""
import sqlite3
import threading
import time
from datetime import datetime

from app import config


class Store:
    def __init__(self, db_path=config.DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS courses(
            id INTEGER PRIMARY KEY, name TEXT, code TEXT, created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY, course_id INTEGER, title TEXT,
            started_at TEXT, ended_at TEXT, status TEXT DEFAULT 'recording')""")
        c.execute("""CREATE TABLE IF NOT EXISTS segments(
            id INTEGER PRIMARY KEY, session_id INTEGER, seq INTEGER,
            t_start REAL, t_end REAL, raw_text TEXT, translated_text TEXT,
            created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS markers(
            id INTEGER PRIMARY KEY, session_id INTEGER, t_marker REAL,
            kind TEXT, note TEXT, created_at TEXT)""")
        # 续录登记：每段录音文件 + 起始墙钟（主录音 ord 隐含=0，续录 ord 从 1 起）。
        # 回听路由「墙钟 → 对应 wav 内位置」依赖此表；主录音起点用 sessions.started_at。
        c.execute("""CREATE TABLE IF NOT EXISTS session_audio(
            session_id INTEGER, ord INTEGER, file TEXT, start_epoch REAL,
            PRIMARY KEY(session_id, ord))""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_seg_session ON segments(session_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mark_session ON markers(session_id)")
        # 课节笔记路径（计入笔记后记住，重新生成覆盖同一文件）
        cols = [r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()]
        if "note_path" not in cols:
            c.execute("ALTER TABLE sessions ADD COLUMN note_path TEXT")
        c.execute("""CREATE TABLE IF NOT EXISTS glossary(
            course_id INTEGER NOT NULL, en TEXT NOT NULL, zh TEXT NOT NULL,
            PRIMARY KEY(course_id, en))""")
        self.conn.commit()

    def create_session(self, title: str = "课堂实录", course_id: int | None = None) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO sessions(course_id, title, started_at, status) VALUES(?,?,?,?)",
                (course_id, title, datetime.now().isoformat(timespec="seconds"), "recording"))
            self.conn.commit()
            return cur.lastrowid

    def end_session(self, sid: int):
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET ended_at=?, status='done' WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), sid))
            self.conn.commit()

    def abort_session(self, sid: int):
        """录音启动失败时标记中止，避免残留 recording 状态。"""
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET ended_at=?, status='aborted' WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), sid))
            self.conn.commit()

    def resume_session(self, sid: int):
        """续录：把已结束的课节重新置为录音中（清 ended_at）。"""
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET ended_at=NULL, status='recording' WHERE id=?",
                (sid,))
            self.conn.commit()

    def add_session_audio(self, sid: int, ord_: int, file: str, start_epoch: float):
        """登记一段录音文件（主录音不登记；续录 ord 从 1 起）。"""
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO session_audio(session_id, ord, file, start_epoch)"
                " VALUES(?,?,?,?)", (sid, ord_, file, start_epoch))
            self.conn.commit()

    def list_session_audio(self, sid: int):
        """续录文件列表 [(ord, file, start_epoch)]，按 ord 升序。"""
        with self._lock:
            return self.conn.execute(
                "SELECT ord, file, start_epoch FROM session_audio"
                " WHERE session_id=? ORDER BY ord", (sid,)).fetchall()

    def max_seq(self, sid: int) -> int:
        """会话当前最大句序号（续录时 seq 从 max+1 继续编号）。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(seq),0) FROM segments WHERE session_id=?", (sid,)).fetchone()
            return row[0] if row else 0

    def recover_stale_sessions(self):
        """启动时清理残留 recording 会话。

        应用启动时不可能有正在录制的会话（录制只在应用运行期间发生），
        因此所有 status='recording' 的会话都是上次异常退出/强杀的残留
        （_finish 的 end_session 没执行成功）。把它们标记为 done，
        否则 UI 会一直显示「录音中」（2026-09-01 session 93 教训：
        用户点停止后强杀进程 → end_session 未执行 → 重启后仍显示录音中）。
        返回清理的会话数。
        """
        with self._lock:
            cur = self.conn.execute(
                "UPDATE sessions SET ended_at=?, status='done'"
                " WHERE status='recording'",
                (datetime.now().isoformat(timespec="seconds"),))
            self.conn.commit()
            return cur.rowcount

    def add_segment(self, sid: int, seq: int, t0: float, t1: float, raw: str, zh: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO segments(session_id, seq, t_start, t_end, raw_text, translated_text, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (sid, seq, t0, t1, raw, zh, datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()

    def count_segments(self, sid: int) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM segments WHERE session_id=?", (sid,)).fetchone()
            return row[0] if row else 0

    def recent_context(self, sid: int, before_seq: int, n: int = 2):
        """取某课节当前定稿句之前的最近 n 句（英中对照）作为翻译背景。

        按 seq 升序返回 [(en, zh), ...]（时间上从旧到新，方便拼 prompt）；
        自动跳过识别失败/翻译失败/空行，避免污染背景。
        """
        with self._lock:
            rows = self.conn.execute(
                "SELECT raw_text, translated_text FROM segments"
                " WHERE session_id=? AND seq<? AND raw_text!=''"
                " AND raw_text NOT LIKE '[ASR错误]%'"
                " AND translated_text NOT LIKE '[翻译失败]%'"
                " ORDER BY seq DESC LIMIT ?",
                (sid, before_seq, n)).fetchall()
        return list(reversed([(r[0], r[1]) for r in rows]))

    def add_marker(self, sid: int, t: float, kind: str = "user", note: str = ""):
        """打点标记：kind='user' 用户打点；kind='pause' 暂停/恢复事件。"""
        with self._lock:
            self.conn.execute(
                "INSERT INTO markers(session_id, t_marker, kind, note, created_at)"
                " VALUES(?,?,?,?,?)",
                (sid, t, kind, note, datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()

    def list_markers(self, sid: int):
        with self._lock:
            return self.conn.execute(
                "SELECT t_marker, kind, note FROM markers WHERE session_id=?"
                " ORDER BY t_marker", (sid,)).fetchall()

    # ---- 课程 ----
    def ensure_courses(self, courses: list[tuple[str, str]]) -> dict[str, int]:
        """courses: [(code, name)]，缺失则插入。返回 {code: id}。"""
        with self._lock:
            mapping = {}
            for code, name in courses:
                row = self.conn.execute(
                    "SELECT id FROM courses WHERE code=?", (code,)).fetchone()
                if row:
                    mapping[code] = row[0]
                else:
                    cur = self.conn.execute(
                        "INSERT INTO courses(name, code, created_at) VALUES(?,?,?)",
                        (name, code, datetime.now().isoformat(timespec="seconds")))
                    mapping[code] = cur.lastrowid
            self.conn.commit()
            return mapping

    def list_courses(self):
        with self._lock:
            return self.conn.execute(
                "SELECT id, code, name FROM courses ORDER BY code").fetchall()

    def get_course(self, cid: int):
        with self._lock:
            return self.conn.execute(
                "SELECT id, code, name FROM courses WHERE id=?", (cid,)).fetchone()

    def add_course(self, code: str, name: str) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO courses(name, code, created_at) VALUES(?,?,?)",
                (name, code, datetime.now().isoformat(timespec="seconds")))
            self.conn.commit()
            return cur.lastrowid

    def rename_course(self, cid: int, code: str, name: str):
        with self._lock:
            self.conn.execute("UPDATE courses SET code=?, name=? WHERE id=?",
                              (code, name, cid))
            self.conn.commit()

    def delete_course(self, cid: int):
        """删除课程：其下会话解除关联（保留数据，归入未分类），避免误删录音。"""
        with self._lock:
            self.conn.execute("UPDATE sessions SET course_id=NULL WHERE course_id=?", (cid,))
            self.conn.execute("DELETE FROM glossary WHERE course_id=?", (cid,))
            self.conn.execute("DELETE FROM courses WHERE id=?", (cid,))
            self.conn.commit()

    def list_sessions(self, course_id: int):
        with self._lock:
            return self.conn.execute(
                "SELECT id, title, started_at, status FROM sessions"
                " WHERE course_id=? ORDER BY id DESC", (course_id,)).fetchall()

    def list_orphan_sessions(self):
        """未关联课程的会话（如历史数据/删除课程后保留的录音）。"""
        with self._lock:
            return self.conn.execute(
                "SELECT id, title, started_at, status FROM sessions"
                " WHERE course_id IS NULL AND status != 'aborted' ORDER BY id DESC").fetchall()

    def session_index(self, sid: int) -> int:
        """第几节：同课程下（未中止的）会话中按创建顺序排第几（1 起）。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT course_id FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row:
                return 1
            cid = row[0]
            if cid is None:
                cur = self.conn.execute(
                    "SELECT COUNT(*) FROM sessions"
                    " WHERE course_id IS NULL AND status != 'aborted' AND id<=?", (sid,))
            else:
                cur = self.conn.execute(
                    "SELECT COUNT(*) FROM sessions"
                    " WHERE course_id=? AND status != 'aborted' AND id<=?", (cid, sid))
            n = cur.fetchone()[0]
            return n if n else 1

    def session_stats(self, sid: int) -> tuple[int, float]:
        """(段数, 时长秒)。时长 = 最后一段结束 - 第一段开始（音频相对时间，不含暂停）。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*), MIN(t_start), MAX(t_end) FROM segments"
                " WHERE session_id=?", (sid,)).fetchone()
            n = row[0] if row else 0
            if n and row[1] is not None and row[2] is not None:
                dur = max(0.0, row[2] - row[1])
            else:
                dur = 0.0
            return n, dur

    def get_session(self, sid: int):
        with self._lock:
            return self.conn.execute(
                "SELECT id, course_id, title, started_at, ended_at, status"
                " FROM sessions WHERE id=?", (sid,)).fetchone()

    def list_segments(self, sid: int):
        """[(seq, t_start, t_end, raw_text, translated_text)] 按 seq 升序。"""
        with self._lock:
            return self.conn.execute(
                "SELECT seq, t_start, t_end, raw_text, translated_text FROM segments"
                " WHERE session_id=? ORDER BY seq", (sid,)).fetchall()

    def get_note_path(self, sid: int) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT note_path FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row or not row[0]:
                return None
            return row[0]

    def set_note_path(self, sid: int, path: str):
        with self._lock:
            self.conn.execute("UPDATE sessions SET note_path=? WHERE id=?", (path, sid))
            self.conn.commit()

    def update_session_title(self, sid: int, title: str):
        with self._lock:
            self.conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, sid))
            self.conn.commit()

    def list_glossary(self, course_id: int | None) -> list[tuple[str, str]]:
        if not course_id:
            return []
        with self._lock:
            return self.conn.execute(
                "SELECT en, zh FROM glossary WHERE course_id=? ORDER BY en COLLATE NOCASE",
                (course_id,)).fetchall()

    def replace_glossary(self, course_id: int, terms: list[tuple[str, str]]):
        with self._lock:
            self.conn.execute("DELETE FROM glossary WHERE course_id=?", (course_id,))
            for en, zh in terms:
                en, zh = (en or "").strip(), (zh or "").strip()
                if en and zh:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO glossary(course_id, en, zh) VALUES(?,?,?)",
                        (course_id, en, zh))
            self.conn.commit()

    def upsert_glossary_terms(self, course_id: int, terms: list[tuple[str, str]]):
        """追加或覆盖指定英文条，不删其它已有术语。"""
        with self._lock:
            for en, zh in terms:
                en, zh = (en or "").strip(), (zh or "").strip()
                if en and zh:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO glossary(course_id, en, zh) VALUES(?,?,?)",
                        (course_id, en, zh))
            self.conn.commit()

    def list_failed_segments(self, sid: int):
        """[(seq, t_start, t_end, raw_text, translated_text)] 翻译失败句。"""
        with self._lock:
            return self.conn.execute(
                "SELECT seq, t_start, t_end, raw_text, translated_text FROM segments"
                " WHERE session_id=? AND translated_text LIKE '[翻译失败]%'"
                " ORDER BY seq", (sid,)).fetchall()

    def update_segment_zh(self, sid: int, seq: int, zh: str):
        with self._lock:
            self.conn.execute(
                "UPDATE segments SET translated_text=? WHERE session_id=? AND seq=?",
                (zh, sid, seq))
            self.conn.commit()

    def export_markdown(self, sid: int, path=None, title=None) -> str:
        """导出为 Obsidian 友好 Markdown（带 frontmatter，中英对照）。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT seq, t_start, raw_text, translated_text FROM segments"
                " WHERE session_id=? ORDER BY seq", (sid,)).fetchall()
            sess = self.conn.execute(
                "SELECT title, started_at FROM sessions WHERE id=?", (sid,)).fetchone()
        path = path or (config.EXPORT_DIR / f"session_{sid}.md")
        path.parent.mkdir(parents=True, exist_ok=True)

        title = title or (sess[0] if sess else f"Session {sid}")
        started = sess[1] if sess else ""
        lines = [
            "---",
            "type: lecture-transcript",
            f"session: {sid}",
            f"title: \"{title}\"",
            f"date: {started}",
            "tags: [transcript]",
            "---",
            "",
        ]
        for _seq, t0, raw, zh in rows:
            ts = time.strftime("%H:%M:%S", time.localtime(t0))
            lines.append(f"**[{ts}]** {zh}")
            if raw:
                lines.append(f"> {raw}")
            lines.append("")

        markers = self.list_markers(sid)
        if markers:
            lines.append("## 时间线标记")
            for t, kind, note in markers:
                ts = time.strftime("%H:%M:%S", time.localtime(t))
                if kind == "user":
                    icon, label = "⭐", note or "重点/疑问"
                else:
                    icon, label = "", note  # 暂停/恢复事件，note 自带图标文案
                lines.append(f"- `{ts}` {icon} {label}".rstrip())
            lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return str(path)

