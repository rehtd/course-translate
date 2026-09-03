"""同传课堂主窗口：课程/会话管理、录制控制、转写查看、搜索、计入笔记。"""
import pathlib
import subprocess
import threading
import time
from datetime import datetime
from urllib.parse import quote

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSplitter, QStatusBar, QStyle,
                               QStyleFactory, QStyledItemDelegate, QVBoxLayout, QWidget)

from app import config, settings
from app.audio_files import (
    compress_session, encoder_available, estimate_m4a_bytes, format_bytes,
    resolve_audio, wav_bytes_total, PROMPT_MIN_BYTES,
)
from app.asr import Transcriber
from app.overlay import ControlChip, SubtitleBar, make_floating
from app.recorder import Recorder
from app.storage import Store
from app.translate import (make_translator, parse_glossary_text,
                           format_glossary_text, translate_with_retry)

DEFAULT_COURSES = [
    ("EF5560", "Fintech and AI in Finance"),
    ("MS5215", "AI-Enhanced BA (Excel+Python)"),
    ("IS6400", "Business Data Analytics"),
    ("IS6335", "Data Visualization"),
    ("IS5113", ""),  # 名称待补
]

_PROVIDER_NAMES = {
    "deepseek": "DeepSeek（课堂翻译，支持术语表）",
    "dashscope": "阿里百炼 Qwen（支持术语表，免费额度）",
    "baidu": "百度翻译（机器翻译，无术语表/上下文）",
    "tencent": "腾讯云机器翻译（待修；无术语表/上下文）",
    "alibaba": "阿里云机器翻译（无术语表/上下文）",
    "ollama": "本地/远程 Ollama（支持术语表，断网可用）",
}

_SESSION_STATUS = {"done": "已完成", "recording": "录制中", "saved": "已保存"}

_ASR_MODES = {
    "realtime": "实时（框内约 5s 切句，字幕短窗跟读）",
    "precise": "精准（框内约 10s 切句 + 环境音过滤，字幕同样短窗）",
}

# 全局主题：浅色现代风，靛蓝主色，录制红/暂停琥珀作为强状态色
_APP_QSS = """
QMainWindow, QDialog { background: #F4F5F7; }
QWidget { font-family: "PingFang SC", "Helvetica Neue"; font-size: 13px; color: #1F2329; }

QComboBox, QLineEdit {
    background: white; border: 1px solid #D8DBE0; border-radius: 6px;
    padding: 5px 8px; selection-background-color: #4F6BED;
}
QComboBox:focus, QLineEdit:focus { border-color: #4F6BED; }
QComboBox::drop-down { border: none; width: 20px; }

QPushButton {
    background: white; border: 1px solid #D8DBE0; border-radius: 6px; padding: 5px 12px;
}
QPushButton:hover { background: #F0F2F5; }
QPushButton:disabled { color: #A8ACB3; background: #F0F1F3; }
QPushButton[accent="true"] {
    background: #4F6BED; color: white; border: none; font-weight: 600;
}
QPushButton[accent="true"]:hover { background: #3F5BDB; }
QPushButton[accent="true"]:disabled { background: #B9C4F2; }
QPushButton[danger="true"] {
    background: #E5484D; color: white; border: none; font-weight: 600;
}
QPushButton[danger="true"]:hover { background: #D13A3F; }
QPushButton[danger="true"]:disabled { background: #F2B8BA; }

QTreeWidget, QListWidget {
    background: white; border: 1px solid #E3E5E9; border-radius: 8px; outline: none;
}
QTreeWidget::item { padding: 5px 6px; border-radius: 4px; }
QTreeWidget::item:selected { background: #E7EDFD; color: #1F2329; }
QTreeWidget::item:hover { background: #F0F2F5; }
QListWidget#courseList { background: white; border: 1px solid #E3E5E9; border-radius: 8px; outline: none; }
QListWidget#courseList::item { padding: 7px 8px; border-radius: 6px; margin: 1px 3px; }
QListWidget#courseList::item:selected { background: #E7EDFD; color: #1F2329; }
QListWidget#courseList::item:hover { background: #F0F2F5; }
QListWidget#sessionList { background: white; border: 1px solid #E3E5E9; border-radius: 8px; outline: none; }
QListWidget#sessionList::item { border-radius: 6px; margin: 1px 3px; }
QListWidget#sessionList::item:selected { background: #E7EDFD; color: #1F2329; }
QListWidget#sessionList::item:hover { background: #F0F2F5; }
QListWidget#transcriptList::item { border: none; padding: 0px; }
QListWidget#transcriptList::item:selected { background: transparent; }

QStatusBar { background: #ECEEF1; color: #5A5F66; border-top: 1px solid #D8DBE0; }
QMenuBar { background: #F4F5F7; color: #1F2329; }
QMenu {
    background: #FFFFFF;
    color: #1F2329;
    border: 1px solid #D8DBE0;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    background: transparent;
    color: #1F2329;
    padding: 6px 20px 6px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #E7EDFD;
    color: #1F2329;
}
QMenu::item:disabled {
    color: #A8ACB3;
}
QMenu::separator {
    height: 1px;
    background: #E3E5E9;
    margin: 4px 8px;
}
QSplitter::handle { background: #E3E5E9; width: 2px; }
QToolTip { background: #1F2329; color: white; border: none; padding: 4px 8px; }
"""


def _context_menu(parent) -> QMenu:
    """浅色右键菜单。macOS 系统深色菜单会无视 QSS，需改用 Fusion 绘制。"""
    menu = QMenu(parent)
    menu.setStyle(QStyleFactory.create("Fusion"))
    return menu


class _PairDelegate(QStyledItemDelegate):
    """回看列表：一句一块，上英下中。只绘制、不建控件，长课也能秒开。"""

    _PAD_X = 14
    _PAD_Y = 10
    _GAP = 4

    def paint(self, painter: QPainter, option, index):
        data = index.data(Qt.UserRole)
        if not isinstance(data, dict):
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = option.rect
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#E7EDFD"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor("#F0F2F5"))
        else:
            painter.fillRect(rect, QColor("#FFFFFF"))
        painter.setPen(QColor("#E7E9ED"))
        painter.drawLine(rect.left() + 8, rect.bottom(), rect.right() - 8, rect.bottom())

        x = rect.x() + self._PAD_X
        y = rect.y() + self._PAD_Y
        w = max(rect.width() - 2 * self._PAD_X, 40)

        if data.get("kind") == "marker":
            font = QFont(option.font)
            font.setPointSize(12)
            painter.setFont(font)
            painter.setPen(QColor("#B8860B"))
            text = index.data(Qt.DisplayRole) or ""
            painter.drawText(QRect(x, y, w, rect.height() - 2 * self._PAD_Y),
                             Qt.TextWordWrap, text)
            painter.restore()
            return

        en = (data.get("en") or "").strip()
        zh = (data.get("zh") or "").strip()
        if en:
            font = QFont(option.font)
            font.setPointSize(13)
            painter.setFont(font)
            painter.setPen(QColor("#6A7078"))
            br = painter.fontMetrics().boundingRect(QRect(0, 0, w, 8000), Qt.TextWordWrap, en)
            painter.drawText(QRect(x, y, w, br.height()), Qt.TextWordWrap, en)
            y += br.height() + (self._GAP if zh else 0)
        if zh:
            font = QFont(option.font)
            font.setPointSize(15)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#1F2329"))
            br = painter.fontMetrics().boundingRect(QRect(0, 0, w, 8000), Qt.TextWordWrap, zh)
            painter.drawText(QRect(x, y, w, br.height()), Qt.TextWordWrap, zh)
        elif not en:
            font = QFont(option.font)
            painter.setFont(font)
            painter.setPen(QColor("#A8ACB3"))
            painter.drawText(QRect(x, y, w, 24), Qt.AlignVCenter, "（空）")
        painter.restore()

    def sizeHint(self, option, index):
        data = index.data(Qt.UserRole)
        if not isinstance(data, dict):
            return super().sizeHint(option, index)
        view = self.parent()
        vw = 0
        if view is not None and hasattr(view, "viewport"):
            vw = view.viewport().width()
        w = max((option.rect.width() or vw) - 2 * self._PAD_X, 80)
        if data.get("kind") == "marker":
            font = QFont(option.font)
            font.setPointSize(12)
            text = index.data(Qt.DisplayRole) or ""
            br = QFontMetrics(font).boundingRect(QRect(0, 0, w, 8000), Qt.TextWordWrap, text)
            return QSize(max(vw, 100), br.height() + 2 * self._PAD_Y)
        en = (data.get("en") or "").strip()
        zh = (data.get("zh") or "").strip()
        h = 2 * self._PAD_Y
        if en:
            font = QFont(option.font)
            font.setPointSize(13)
            h += QFontMetrics(font).boundingRect(
                QRect(0, 0, w, 8000), Qt.TextWordWrap, en).height()
        if zh:
            if en:
                h += self._GAP
            font = QFont(option.font)
            font.setPointSize(15)
            font.setBold(True)
            h += QFontMetrics(font).boundingRect(
                QRect(0, 0, w, 8000), Qt.TextWordWrap, zh).height()
        if not en and not zh:
            h += 24
        return QSize(max(vw, 100), max(h, 44))


class MainWindow(QMainWindow):
    note_ready = Signal(object)
    note_failed = Signal(str)
    retry_finished = Signal(int, int, str)  # sid, n_ok, err
    gloss_ready = Signal(object)
    gloss_failed = Signal(str)
    compress_progress = Signal(str)
    compress_finished = Signal(object)

    def __init__(self, store: Store, *, warmup: bool = True):
        super().__init__()
        self.store = store
        # 启动时优先读取设置里保存的翻译引擎，避免重启后悄悄退回 DeepSeek
        self.tsl = make_translator(settings.load().get("translate_provider")
                                   or config.TRANSLATE_PROVIDER)
        self.recorder: Recorder | None = None
        self.bar: SubtitleBar | None = None
        self.chip: ControlChip | None = None
        self.current_session = None
        self.audio_path = None
        self._audio_routes = None   # 当前会话「墙钟 → wav」路由表（主录音+续录）
        self._cur_course_id = None   # 当前工作区课程（点左栏切换）
        self._model_ready = False
        self._model_error = ""
        self._recording_active = False
        self._full_dlg = None
        self._workspace = "review"   # record | review

        self.setWindowTitle("同传课堂")
        self.resize(1080, 680)
        self.setStyleSheet(_APP_QSS)
        self._build_ui()
        self._seed_courses()
        if warmup:
            self._warmup_model()
        else:
            self._model_ready = True
        self._pending_note = None
        self._retrying = False
        self._extracting_gloss = False
        self._compressing = False
        self.note_ready.connect(self._on_note_ready)
        self.note_failed.connect(self._on_note_failed)
        self.retry_finished.connect(self._on_retry_finished)
        self.gloss_ready.connect(self._on_gloss_ready)
        self.gloss_failed.connect(self._on_gloss_failed)
        self.compress_progress.connect(self.status.showMessage)
        self.compress_finished.connect(self._on_compress_finished)
        self._setup_ui_controls()
        # 录制中：点 Dock 第一下=只留字幕，第二下=完整窗口
        from PySide6.QtWidgets import QApplication
        QApplication.instance().applicationStateChanged.connect(self._on_app_state)

    # ---------- UI ----------
    def _build_ui(self):
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.on_pause)
        self.btn_stop = QPushButton("⏹ 结束")
        self.btn_stop.setProperty("danger", True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.on_stop)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 搜索译文 / 原文…")
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self._apply_filter)

        self.btn_note = QPushButton("📝 计入笔记")
        self.btn_note.setProperty("accent", True)
        self.btn_note.setEnabled(False)
        self.btn_note.clicked.connect(self.on_save_note)
        self.btn_export = QPushButton("导出")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.on_export)
        self.btn_full = QPushButton("📜 全文")
        self.btn_full.setEnabled(False)
        self.btn_full.setToolTip("从头到尾的完整记录 · 可切换 英文/中文/双语 显示")
        self.btn_full.clicked.connect(self.on_full)
        self.btn_settings = QPushButton("⚙ 设置")
        self.btn_settings.clicked.connect(self.on_settings)

        top = QHBoxLayout()
        top.setContentsMargins(4, 8, 4, 4)
        top.setSpacing(8)
        top.addWidget(self.btn_pause)
        top.addWidget(self.btn_stop)
        top.addStretch(1)
        top.addWidget(self.search)
        top.addWidget(self.btn_note)
        top.addWidget(self.btn_export)
        top.addWidget(self.btn_full)
        top.addWidget(self.btn_settings)

        # 录制状态横幅：录制中=红色呼吸，暂停=琥珀，空闲=隐藏
        self.banner = QFrame()
        self.banner.setVisible(False)
        self.banner.setFixedHeight(40)
        self.banner_label = QLabel("")
        self.banner_label.setAlignment(Qt.AlignCenter)
        self.banner_label.setStyleSheet(
            "color: white; font-size: 15px; font-weight: 700; background: transparent;")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.addWidget(self.banner_label)
        self._banner_on = True
        self._banner_timer = QTimer(self)
        self._banner_timer.timeout.connect(self._tick_banner)
        self._rec_started_at = 0.0
        self._rec_accum = 0.0  # 暂停累计秒数

        # 左栏：课程列表（点选一门课 = 整个工作区切换为该课程）
        self.course_list = QListWidget()
        self.course_list.setObjectName("courseList")
        self.course_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.course_list.customContextMenuRequested.connect(self._on_course_menu)
        self.course_list.itemClicked.connect(self._on_course_click)
        self.btn_add_course = QPushButton("＋ 课程")
        self.btn_add_course.setToolTip("新增课程/分类（会议、访谈等也可新增）")
        self.btn_add_course.clicked.connect(self.on_add_course)
        left_panel = QWidget()
        ll = QVBoxLayout(left_panel)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        ll.addWidget(self.course_list)
        ll.addWidget(self.btn_add_course)

        # 中栏：当前课程的历史课节 + 新建/续录入口（录制入口在这里）
        self.btn_new_session = QPushButton("＋ 新建一节课")
        self.btn_new_session.setProperty("accent", True)
        self.btn_new_session.setToolTip("在当前课程下开始新一节录制")
        self.btn_new_session.clicked.connect(self.on_record)
        self.btn_continue = QPushButton("▶ 继续录制")
        self.btn_continue.setToolTip("选中已结束的课节后可用：重新打开录音，新内容追加到同一节")
        self.btn_continue.clicked.connect(self.on_continue)
        self.btn_continue.setEnabled(False)
        self.session_list = QListWidget()
        self.session_list.setObjectName("sessionList")
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._on_session_menu)
        self.session_list.itemClicked.connect(self._on_session_click)
        mid_panel = QWidget()
        ml = QVBoxLayout(mid_panel)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(6)
        ml.addWidget(self.btn_new_session)
        ml.addWidget(self.btn_continue)
        ml.addWidget(self.session_list)

        # 回看主区：一句一块（上英下中），委托绘制、不建富卡片
        self.transcript = QListWidget()
        self.transcript.setObjectName("transcriptList")
        self.transcript.setSpacing(0)
        self.transcript.setUniformItemSizes(False)
        self.transcript.setWordWrap(True)
        self.transcript.setTextElideMode(Qt.ElideNone)
        self.transcript.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.transcript.setItemDelegate(_PairDelegate(self.transcript))
        self.transcript.setStyleSheet(
            "QListWidget { background: #F4F5F7; border: 1px solid #E3E5E9; border-radius: 8px; padding: 4px; }")
        self.transcript.itemDoubleClicked.connect(self._on_card_dblclick)
        # sticky 滚动：记录「用户是否盯着底部」。addItem 后若用户仍在底部则
        # 跟随滚动；用户手动滚上去看历史则不打扰（与全文对话框 _at_bottom 一致）。
        # 不能用「addItem 后实时判断 maximum-value」——addItem 时 maximum 已含
        # 新卡高度（60-100px），恒 >24px 阈值，会导致永远不滚动（暂停恢复后
        # 「数据在入库但 UI 看不见」的根因）。
        self._transcript_sticky = True
        self.transcript.verticalScrollBar().valueChanged.connect(self._on_transcript_scrolled)
        self._partial_item = None
        self._partial_card = None
        self._placeholder_item = None
        self._show_placeholder("在中间栏选择课节查看转写，或点击「＋ 新建一节课」开始录制")

        # 右侧：英文原文 / 中文译文 双积累框（对照在框内看，悬浮字幕只跟读英文）
        def _make_box(title: str, placeholder: str, mono: bool = False):
            panel = QWidget()
            v = QVBoxLayout(panel)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            t = QLabel(title)
            t.setStyleSheet(
                "color: #4F6BED; font-size: 12px; font-weight: 700; padding: 2px 4px;")
            box = QPlainTextEdit()
            box.setReadOnly(True)
            box.setPlaceholderText(placeholder)
            font = "Menlo, monospace" if mono else "'PingFang SC', 'Helvetica Neue'"
            box.setStyleSheet(
                "QPlainTextEdit { background: #FBFCFE; border: 1px solid #E3E5E9;"
                "border-radius: 8px; padding: 10px; color: #1F2329; font-size: 15px;"
                f"font-family: {font}; }}")
            v.addWidget(t)
            v.addWidget(box)
            return panel, box

        self.en_panel, self.en_box = _make_box(
            "英文原文", "句子定稿后，英文原文按顺序累积在这里…", mono=True)
        self.zh_panel, self.zh_box = _make_box(
            "中文译文", "句子定稿后，中文译文按顺序累积在这里…")
        self.right_split = QSplitter(Qt.Vertical)
        self.right_split.addWidget(self.en_panel)
        self.right_split.addWidget(self.zh_panel)
        self.right_split.setSizes([280, 280])
        self.right_split.setChildrenCollapsible(False)

        self._split = QSplitter(Qt.Horizontal)
        self._split.addWidget(left_panel)
        self._split.addWidget(mid_panel)
        self._split.addWidget(self.transcript)
        self._split.addWidget(self.right_split)
        self._split.setChildrenCollapsible(False)
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 0)
        self._split.setStretchFactor(2, 1)
        self._split.setStretchFactor(3, 1)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(8, 0, 8, 4)
        lay.setSpacing(4)
        lay.addLayout(top)
        lay.addWidget(self.banner)
        lay.addWidget(self._split)
        self.setCentralWidget(central)
        self._apply_workspace("review")

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪 · 等待选择课程并开始录制")

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(QAudioOutput(self))
        self.player.positionChanged.connect(self._on_pos)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self._pending_pos = None   # 待定位（media 加载完成后再 seek，防大文件首次回听失效）

    def _apply_workspace(self, mode: str):
        """record = 上英下中大框；review = 一句一块对照列表。"""
        self._workspace = mode
        if mode == "record":
            self.transcript.hide()
            self.right_split.show()
            self._split.setSizes([140, 200, 0, 1000])
            h = max(self.right_split.height(), 360)
            self.right_split.setSizes([h // 2, h - h // 2])
        else:
            self.right_split.hide()
            self.transcript.show()
            self._split.setSizes([140, 200, 1000, 0])

    # ---------- 录制横幅 ----------
    def _set_banner(self, mode: str, extra: str = ""):
        """mode: recording / paused / saving / off"""
        if mode == "off":
            self._banner_timer.stop()
            self.banner.setVisible(False)
            return
        self.banner.setVisible(True)
        styles = {
            "recording": ("#E5484D", "● 录制中"),
            "paused": ("#E8A33D", "⏸ 已暂停"),
            "saving": ("#4F6BED", "⏳ 保存中…"),
        }
        color, text = styles[mode]
        self.banner.setStyleSheet(
            f"QFrame {{ background: {color}; border-radius: 8px; }}")
        self._banner_base = text
        self._banner_extra = extra
        self._tick_banner()
        if mode in ("recording", "paused"):
            self._banner_timer.start(500)
        else:
            self._banner_timer.stop()

    def _tick_banner(self):
        elapsed = ""
        if self._rec_started_at:
            secs = int(self._rec_accum)
            if getattr(self, "_rec_state", "") == "recording":
                secs += int(time.time() - self._rec_started_at)
            elapsed = f"  {secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"
        dot = getattr(self, "_banner_base", "")
        # 录制中红点呼吸闪烁
        if self._banner_timer.isActive() and getattr(self, "_banner_base", "") == "● 录制中":
            self._banner_on = not self._banner_on
            dot = "● 录制中" if self._banner_on else "○ 录制中"
        self.banner_label.setText(f"{dot}{elapsed}    {getattr(self, '_banner_extra', '')}")

    # ---------- 转写卡片 ----------
    def _show_placeholder(self, text: str):
        if self._placeholder_item is None:
            self._placeholder_item = QListWidgetItem()
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #A8ACB3; font-size: 14px; background: transparent; padding: 40px;")
            self.transcript.addItem(self._placeholder_item)
            self.transcript.setItemWidget(self._placeholder_item, lbl)
            self._placeholder_item.setSizeHint(lbl.sizeHint())

    def _clear_transcript(self):
        self.transcript.setUpdatesEnabled(False)
        self.transcript.clear()
        self.transcript.setUpdatesEnabled(True)
        self.en_box.clear()
        self.zh_box.clear()
        self._partial_item = self._partial_card = None
        self._placeholder_item = None
        # 新会话/切课/加载历史后默认回到底部跟随；_load_session 末尾 scrollToTop
        # 会经 valueChanged 把 sticky 翻转为 False，不影响「看历史不打扰」
        self._transcript_sticky = True

    def _drop_placeholder(self):
        if self._placeholder_item is not None:
            self.transcript.takeItem(self.transcript.row(self._placeholder_item))
            self._placeholder_item = None

    def _add_segment_card(self, t0, t1, zh, en, scroll=True, *,
                         defer_reflow=True, accumulate=True):
        self._drop_placeholder()
        card = _SegmentCard(t0, t1, zh, en)
        card.play_clicked.connect(lambda c=card: self._play_range(c.t0, c.t1))
        item = QListWidgetItem()
        # 定稿可能晚于下一句的字幕草稿：插到「识别中」卡片前面，不把草稿顶掉
        if self._partial_item is not None:
            row = self.transcript.row(self._partial_item)
            self.transcript.insertItem(max(row, 0), item)
        else:
            self.transcript.addItem(item)
        self.transcript.setItemWidget(item, card)
        item.setSizeHint(card.sizeHint())
        if defer_reflow:
            QTimer.singleShot(0, lambda it=item, c=card: self._reflow_one(it, c))
        if scroll and self._transcript_sticky:
            # sticky 状态在 addItem 前记录，避免「addItem 后 maximum 已含新卡高」导致永不到底
            self.transcript.scrollToBottom()
        self._apply_filter_to_item(item, card)
        # 定稿句的中英各自累积到右侧对应框（partial 不累积，避免碎片）
        if accumulate and not card.partial:
            if en and not en.startswith("[ASR错误]"):
                self._append_en(en)
            if zh and not zh.startswith("（未识别") and not zh.startswith("[翻译失败]"):
                self._append_zh(zh)
        return item, card

    def _append_en(self, en):
        """右侧英文原文累积区：只追加，带空行分隔，自动滚到底。"""
        self.en_box.appendPlainText(en)
        self.en_box.appendPlainText("")
        sb = self.en_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append_zh(self, zh):
        """右侧中文译文累积区：只追加，带空行分隔，自动滚到底。"""
        self.zh_box.appendPlainText(zh)
        self.zh_box.appendPlainText("")
        sb = self.zh_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _add_marker_card(self, kind, note, t):
        self._drop_placeholder()
        ts = time.strftime("%H:%M:%S", time.localtime(t))
        icon = "⭐" if kind == "user" else "⏸"
        lbl = QLabel(f"{icon}  {ts}  {note}")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "color: #B8860B; background: #FFF7E6; border: 1px solid #F0DFB8;"
            "border-radius: 6px; padding: 3px 10px; font-size: 12px;")
        item = QListWidgetItem()
        self.transcript.addItem(item)
        self.transcript.setItemWidget(item, lbl)
        item.setSizeHint(lbl.sizeHint())
        if self._transcript_sticky:
            self.transcript.scrollToBottom()

    def _on_transcript_scrolled(self, _value):
        """用户手动滚动时更新 sticky 状态：停在底部附近=跟随，滚走=不打扰。"""
        sb = self.transcript.verticalScrollBar()
        self._transcript_sticky = sb.maximum() - sb.value() < 24

    def _upsert_partial(self, en, zh):
        # 实时草稿只上屏英文（zh 恒空），中文等定稿后再进框
        zh = ""
        if self._partial_item is None:
            self._drop_placeholder()
            self._partial_card = _SegmentCard(0, 0, zh, en, partial=True)
            self._partial_item = QListWidgetItem()
            self.transcript.addItem(self._partial_item)
            self.transcript.setItemWidget(self._partial_item, self._partial_card)
        else:
            self._partial_card.set_text(zh, en)
        self._partial_item.setSizeHint(self._partial_card.sizeHint())
        QTimer.singleShot(0, self._reflow_partial)
        if self._transcript_sticky:
            self.transcript.scrollToBottom()

    def _reflow_one(self, item, card):
        """只重算一张卡高度（切回前台时积压的定稿不应把全部卡片刷一遍）。"""
        if item is None or not isinstance(card, _SegmentCard):
            return
        from PySide6.QtCore import QSize
        vw = max(self.transcript.viewport().width() - 20, 200)
        h = card.frame_height_for(vw)
        if h > 0:
            item.setSizeHint(QSize(vw, h))

    def _reflow_partial(self):
        self._reflow_one(self._partial_item, self._partial_card)

    def _reflow_all(self):
        """窗口变宽时重算高度：直播卡片逐张测；回看列表交给委托 sizeHint。"""
        if not hasattr(self, "transcript") or self.transcript.isHidden():
            return
        n = self.transcript.count()
        if n == 0:
            return
        sample = min(8, n)
        if any(
            isinstance(self.transcript.itemWidget(self.transcript.item(i)), _SegmentCard)
            for i in range(sample)
        ):
            vw = max(self.transcript.viewport().width() - 20, 200)
            for i in range(n):
                item = self.transcript.item(i)
                w = self.transcript.itemWidget(item)
                if isinstance(w, _SegmentCard):
                    h = w.frame_height_for(vw)
                    if h > 0:
                        item.setSizeHint(QSize(vw, h))
            return
        self.transcript.doItemsLayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._reflow_all)

    def _drop_partial(self):
        if self._partial_item is not None:
            self.transcript.takeItem(self.transcript.row(self._partial_item))
            self._partial_item = self._partial_card = None

    # ---------- 数据 ----------
    def _seed_courses(self):
        self.store.ensure_courses(DEFAULT_COURSES)
        self._reload_course_list()
        # 默认进入第一门课的工作区（减少空态；无课则保持未选中）
        if self.course_list.count() > 0:
            self.course_list.setCurrentRow(0)
            self._on_course_click(self.course_list.item(0))
        else:
            self._reload_session_list()

    def _reload_course_list(self):
        cur = self._cur_course_id
        self.course_list.clear()
        for cid, code, name in self.store.list_courses():
            item = QListWidgetItem(f"{code} {name}".strip())
            item.setData(Qt.UserRole, cid)
            self.course_list.addItem(item)
        item = QListWidgetItem("📁 未分类")
        item.setData(Qt.UserRole, None)
        item.setForeground(Qt.gray)
        self.course_list.addItem(item)
        for i in range(self.course_list.count()):
            if self.course_list.item(i).data(Qt.UserRole) == cur:
                self.course_list.setCurrentRow(i)
                break

    def _course_label(self) -> str:
        cid = self._cur_course_id
        if cid is None:
            return "未分类"
        c = self.store.get_course(cid)
        return f"{c[1]} {c[2]}".strip() if c else "未分类"

    def _reload_session_list(self, select_sid=None):
        self.session_list.clear()
        cid = self._cur_course_id
        sessions = (self.store.list_sessions(cid)
                    if cid is not None else self.store.list_orphan_sessions())
        for sid, title, started, status in sessions:
            if status == "aborted":
                continue
            n, dur = self.store.session_stats(sid)
            idx = self.store.session_index(sid)
            row = _SessionRow(idx, started, dur, n, status)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, sid)
            item.setSizeHint(row.sizeHint())
            self.session_list.addItem(item)
            self.session_list.setItemWidget(item, row)
            if sid == select_sid:
                self.session_list.setCurrentItem(item)

    def _warmup_model(self):
        self.status.showMessage(
            f"正在加载识别模型（字幕 {config.ASR_PARTIAL_MODEL} · 框内 {config.ASR_MODEL}）…")
        self.btn_new_session.setEnabled(False)

        def load():
            try:
                # 草稿用轻量模型跟读；定稿用 ASR_MODEL
                self.tr = Transcriber(config.ASR_PARTIAL_MODEL, config.ASR_BEAM,
                                      config.ASR_LANGUAGE)
                if config.ASR_MODEL != config.ASR_PARTIAL_MODEL:
                    self.tr_final = Transcriber(config.ASR_MODEL, config.ASR_BEAM,
                                                config.ASR_LANGUAGE)
                else:
                    self.tr_final = None   # 同模型则单轨（复用 tr）
                self._model_ready = True
            except Exception as e:  # noqa: BLE001
                self._model_error = str(e)

        threading.Thread(target=load, daemon=True).start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_model)
        self._timer.start(300)

    def _check_model(self):
        if self._model_ready:
            self._timer.stop()
            self.btn_new_session.setEnabled(True)
            self.status.showMessage("就绪 · 选择课程后点击「＋ 新建一节课」开始录制")
        elif self._model_error:
            self._timer.stop()
            self.btn_new_session.setEnabled(False)
            self.status.showMessage(f"模型加载失败: {self._model_error}")

    # ---------- 字幕控制入口（应用菜单，无快捷键、无菜单栏图标） ----------
    def _setup_ui_controls(self):
        from PySide6.QtGui import QAction
        view_menu = self.menuBar().addMenu("字幕")
        act = QAction("显示/隐藏字幕", self)
        act.triggered.connect(self._toggle_overlay)
        view_menu.addAction(act)

    def _toggle_overlay(self):
        # 防抖：多个入口可能同时触发
        now = time.time()
        if now - getattr(self, "_last_toggle", 0.0) < 0.3:
            return
        self._last_toggle = now
        if self.bar is None:
            self.status.showMessage("先开始录制，字幕才会出现", 3000)
            return
        if not self._recording_active:
            self.status.showMessage("当前没有进行中的录音", 3000)
            return
        if self.bar.isVisible():
            self.bar.hide()          # 只隐藏字幕，控制条保留，确保永远能恢复
            self.status.showMessage("字幕已隐藏（点控制条「字」恢复）", 3000)
        else:
            self.bar.show()
            self.status.showMessage("字幕已显示", 3000)

    def _on_app_state(self, state):
        """录制中切后台再回来：只重设字幕浮动层，不要 hide/show 主窗口。

        字幕点击穿透，Cmd+Tab / 从 PPT 切回来时 widgetAt 经常是 None；
        若据此 hide() 主窗口，再 activateWindow 会重入 ApplicationActive，
        看起来像卡死。字幕靠浮动层级保持可见，切应用不必动主窗口。
        """
        if state != Qt.ApplicationActive or not self._recording_active:
            return
        # 等 Cocoa 激活走完再碰 NSWindow，避免和 winId/setLevel 抢主线程
        QTimer.singleShot(250, self._reassert_overlay_level)

    def _reassert_overlay_level(self):
        if not self._recording_active:
            return
        try:
            if self.bar is not None and self.bar.isVisible():
                make_floating(self.bar)
            if self.chip is not None and self.chip.isVisible():
                make_floating(self.chip)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 录制控制 ----------
    def on_record(self):
        cid = self._cur_course_id
        if not self._model_ready:
            self.status.showMessage("识别模型还在加载中，请稍候再试…", 3000)
            return
        if cid is None:
            # 未分类工作区：录音不归入任何课程，给出一次引导（默认继续，不打断）
            ret = QMessageBox.question(
                self, "未选择课程",
                "当前在「未分类」工作区，新建录音不会归入任何课程。\n"
                "建议先在左侧选择一门课程（会议/访谈等临时录音可继续）。\n\n仍要继续录制？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ret != QMessageBox.Yes:
                return
        # 自动命名「第 N 节」，让历史列表一眼区分第一/二节课
        sessions = (self.store.list_sessions(cid)
                    if cid is not None else self.store.list_orphan_sessions())
        n = sum(1 for s in sessions if s[3] != "aborted") + 1
        title = f"第 {n} 节"
        self._ensure_recorder()
        self._clear_transcript()
        self.current_session = None
        self.audio_path = None
        self._audio_routes = None
        self._rec_started_at = time.time()
        self._rec_accum = 0.0
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.reset()
            self._full_dlg.set_info("● 录制中… 正在实时追加")
        try:
            self.recorder.start(course_id=cid, title=title)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "无法开始录音",
                f"打开麦克风失败：{e}\n\n请检查：\n"
                "1. 系统设置 → 隐私与安全性 → 麦克风 → 允许「同传课堂」\n"
                "2. 没有其他应用独占麦克风（如视频会议）\n"
                "3. 重启应用后重试")
            return
        self._reload_session_list()   # 中栏立即出现「● 录制中 · 第 N 节」
        self._apply_workspace("record")
        self._show_overlay()
        self.status.showMessage(f"● 录制中：{self._course_label()} · {title}（右下角控制条 ⏸ 暂停 / ⏹ 结束）")

    def _ensure_recorder(self):
        """惰性创建 Recorder 并接好信号（录制/续录共用同一实例）。"""
        if self.recorder is None:
            self.recorder = Recorder(self.store, self.tr, self.tsl,
                                     tr_final=getattr(self, "tr_final", None))
            self.recorder.seg_finalized.connect(self._on_seg)
            self.recorder.partial_ready.connect(self._on_partial)
            self.recorder.marker_added.connect(self._on_marker)
            self.recorder.state_changed.connect(self._on_state)
            self.recorder.session_done.connect(self._on_session_done)
        # 设置里的识别模式在下一次录制生效（录制中改设置不影响本次）
        self.recorder.asr_mode = settings.load().get("asr_mode", "realtime")

    def on_continue(self):
        """续录：把已结束的课节重新打开，追加录制到同一节。"""
        sid = self.current_session
        if sid is None or self._recording_active:
            return
        sess = self.store.get_session(sid)
        title = sess[2] if sess else "课堂实录"
        ret = QMessageBox.question(
            self, "继续录制",
            f"继续录制到「{title}」？\n"
            "新内容会追加到这一节（录音另存新文件，结束后合并为一节）。\n\n"
            "课间休息请用暂停 ⏸，不需要结束。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self._ensure_recorder()
        self._clear_transcript()
        self.current_session = None
        self.audio_path = None
        self._audio_routes = None
        self._rec_started_at = time.time()
        self._rec_accum = 0.0
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.reset()
            self._full_dlg.set_info("● 续录中… 正在实时追加")
        try:
            self.recorder.continue_session(sid)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "无法继续录音",
                f"打开麦克风失败：{e}\n\n请检查：\n"
                "1. 系统设置 → 隐私与安全性 → 麦克风 → 允许「同传课堂」\n"
                "2. 没有其他应用独占麦克风（如视频会议）\n"
                "3. 重启应用后重试")
            return
        self._reload_session_list(select_sid=sid)   # 该课节回到「● 录制中」状态
        self._fill_record_boxes(sid)
        self._apply_workspace("record")
        self._show_overlay()
        self.status.showMessage(f"● 续录中：{self._course_label()} · {title}（右下角控制条 ⏸ 暂停 / ⏹ 结束）")

    def on_pause(self):
        if self.recorder:
            self.recorder.toggle_pause()

    def on_stop(self):
        if self.recorder is None or self.recorder.session_id is None:
            return
        ret = QMessageBox.question(
            self, "结束录音", "确定结束本次录音并保存吗？\n（课间休息请用暂停 ⏸；结束后想补录可点「▶ 继续录制」）",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.recorder.stop()

    def _fill_record_boxes(self, sid):
        """续录：把已有英/中灌进大框，新定稿接着往下追加。"""
        rows = self.store.conn.execute(
            "SELECT translated_text, raw_text FROM segments"
            " WHERE session_id=? ORDER BY seq", (sid,)).fetchall()
        ens, zhs = [], []
        for zh, en in rows:
            if en and not en.startswith("[ASR错误]"):
                ens.append(en)
            if (zh and not zh.startswith("（未识别")
                    and not zh.startswith("[翻译失败]")):
                zhs.append(zh)
        self.en_box.setPlainText("\n\n".join(ens) + ("\n" if ens else ""))
        self.zh_box.setPlainText("\n\n".join(zhs) + ("\n" if zhs else ""))
        for box in (self.en_box, self.zh_box):
            sb = box.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _show_overlay(self):
        if self.bar is None:
            self.bar = SubtitleBar()
            self.chip = ControlChip()
            self.chip.on_pause_toggle = lambda: self.recorder and self.recorder.toggle_pause()
            self.chip.on_mark = lambda: self.recorder and self.recorder.mark()
            self.chip.on_stop = self.on_stop
            self.chip.on_toggle = self._toggle_overlay
        self.bar.update_text("", "等待老师讲课…")
        self.bar.show()
        self.chip.show()
        # 应用失活时字幕窗保持可见（Qt 原生机制，安全）
        make_floating(self.bar)
        make_floating(self.chip)

    def _hide_overlay(self):
        if self.bar:
            self.bar.hide()
            self.chip.hide()

    # ---------- Recorder 信号 ----------
    def _on_seg(self, seq, t0, t1, en, zh):
        # 定稿只进上英下中大框（准、可慢）。悬浮字幕只跟 partial，
        # 不把晚到的精修句写回字幕——否则会把正在跟读的下一句拽回去。
        if self._partial_card is not None:
            pend = (self._partial_card.en_text or "").strip().lower()
            fin = (en or "").strip().lower()
            same = bool(pend and fin) and (
                fin[:32] in pend or pend[:32] in fin or pend.startswith(fin[:24]))
            if same:
                self._drop_partial()
        if en and not en.startswith("[ASR错误]"):
            self._append_en(en)
        if (zh and not zh.startswith("（未识别")
                and not zh.startswith("[翻译失败]")):
            self._append_zh(zh)
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.add("seg", seq, t0, zh, en)

    def _on_partial(self, en, zh):
        if self.bar:
            self.bar.update_partial(en, zh)
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.add("partial", 0, 0, zh, en)

    def _on_marker(self, kind, note, t):
        ts = time.strftime("%H:%M:%S", time.localtime(t))
        icon = "⭐" if kind == "user" else "⏸"
        self.status.showMessage(f"{icon} {ts} {note}", 3000)
        if not self._recording_active:
            self._add_marker_card(kind, note, t)
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.add("marker", 0, t, "", "", f"{icon} {note}")
        if self.bar is None:
            return
        if kind == "user":
            self._flash_mark()

    def _flash_mark(self):
        if self.chip:
            self.chip.mark_btn.setText("✓")
            QTimer.singleShot(500, lambda: self.chip.mark_btn.setText("★"))

    def _on_state(self, state):
        rec = state == "recording"
        paused = state == "paused"
        prev = getattr(self, "_rec_state", "idle")
        self._rec_state = state
        self._recording_active = rec or paused
        # 暂停/恢复的计时累计
        if paused and prev == "recording" and self._rec_started_at:
            self._rec_accum += time.time() - self._rec_started_at
        elif rec and prev == "paused":
            self._rec_started_at = time.time()
        # 新建课节按钮仅在空闲时可用；暂停按钮在 录制中/已暂停 都可点（切换用）
        self.btn_new_session.setEnabled(self._model_ready and state == "idle")
        self.btn_continue.setEnabled(
            self._model_ready and state == "idle" and self.current_session is not None)
        self.btn_pause.setEnabled(rec or paused)
        self.btn_pause.setText("⏸ 暂停" if rec else ("▶ 继续" if paused else "⏸ 暂停"))
        self.btn_pause.setStyleSheet(
            "background: #E8A33D; color: white; border: none; border-radius: 6px; "
            "padding: 5px 12px; font-weight: 600;" if paused else "")
        self.btn_stop.setEnabled(rec or paused)
        if rec or paused:
            self.btn_full.setEnabled(True)
        course_label = self._course_label()
        if paused:
            self.status.showMessage("⏸ 已暂停 · 点「▶ 继续」恢复，或「结束」保存", 0)
            self._set_banner("paused", course_label)
            if self.chip:
                self.chip.set_paused(True)
            if self.bar:
                self.bar.show_paused(True)
        elif rec:
            self.status.showMessage("● 录制中…", 0)
            self._set_banner("recording", course_label)
            if self.chip:
                self.chip.set_paused(False)
            if self.bar:
                self.bar.show_paused(False)
            if prev == "paused":
                # 用户按「继续」= 回到实时字幕：强制回到底部并恢复跟随，
                # 避免恢复后新卡 addItem 但视口停在暂停前位置（“继续后看不到”）
                self._transcript_sticky = True
                self.transcript.scrollToBottom()
        if state == "saving":
            self.status.showMessage("⏳ 保存中…")
            self._set_banner("saving")
            if self.chip:
                self.chip.status.setText("⏳ 保存中…")
        elif state == "idle":
            self.status.showMessage("就绪 · 选择课程后点击「＋ 新建一节课」")
            self._set_banner("off")
            self._rec_started_at = 0.0
            self._rec_accum = 0.0

    def _on_session_done(self, sid):
        self._hide_overlay()
        self.current_session = sid
        sess = self.store.get_session(sid)
        cid = sess[1] if sess else None
        self._bind_session_audio(sid)
        if cid:
            course = self.store.get_course(cid)
            code = course[1] if course else ""
            self.status.showMessage(f"已保存 · 计入笔记到 {code}（点「计入笔记」选择）")
        self._load_session(sid)
        self.btn_note.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_full.setEnabled(True)
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.load_session(sid)
        # 课节列表刷新并选中刚完成的这节课（时长/段数更新）
        self._reload_session_list(select_sid=sid)
        self.status.showMessage(f"✅ 已保存：{self._course_label()} · {sess[2] if sess else ''}（可「计入笔记」）", 5000)
        QTimer.singleShot(0, lambda: self._maybe_offer_compress(sid))

    # ---------- 全文记录 ----------
    def on_full(self):
        if self._full_dlg is None or not self._full_dlg.isVisible():
            self._full_dlg = _TranscriptDialog(self)
            self._full_dlg.show()
        sid = (self.recorder.session_id
               if (self._recording_active and self.recorder is not None)
               else self.current_session)
        if sid:
            self._full_dlg.load_session(sid)
        else:
            self._full_dlg.reset()
            self._full_dlg.set_info("选择左侧会话，或录制后查看完整记录")
        self._full_dlg.raise_()
        self._full_dlg.activateWindow()

    # ---------- 查看 ----------
    def _on_course_click(self, item):
        """点课程 = 整个工作区切换为该课程（递进：课程 → 课节 → 转写）。"""
        if self._recording_active:
            self.status.showMessage("录制中不能切换课程，请先结束", 3000)
            self._reload_course_list()
            return
        self._cur_course_id = item.data(Qt.UserRole)
        self.current_session = None
        self.audio_path = None
        self._audio_routes = None
        self.btn_continue.setEnabled(False)
        self._clear_transcript()
        self._apply_workspace("review")
        self._reload_session_list()
        if self.session_list.count() == 0:
            self._show_placeholder(
                f"「{self._course_label()}」还没有课节\n\n点击上方「＋ 新建一节课」开始第一节课录制")
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.reset()
            self._full_dlg.set_info(self._course_label())
        self.status.showMessage(f"已切换到：{self._course_label()}", 3000)

    def _on_session_click(self, item):
        if self._recording_active:
            sid_now = self.recorder.session_id if self.recorder else None
            self._reload_session_list(select_sid=sid_now)
            self.status.showMessage("录制中不能切换课节，请先结束", 3000)
            return
        sid = item.data(Qt.UserRole)
        if sid is None:
            return
        self.current_session = sid
        self._bind_session_audio(sid)
        self.btn_continue.setEnabled(not self._recording_active)
        self._load_session(sid)
        self.btn_note.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_full.setEnabled(True)
        if self._full_dlg and self._full_dlg.isVisible():
            self._full_dlg.load_session(sid)

    def _load_session(self, sid):
        self._apply_workspace("review")
        self._clear_transcript()
        rows = self.store.conn.execute(
            "SELECT seq, t_start, t_end, translated_text, raw_text FROM segments"
            " WHERE session_id=? ORDER BY seq", (sid,)).fetchall()
        if not rows:
            self._show_placeholder("本会话没有转写内容")
            self._refresh_status()
            return
        sticky = self._transcript_sticky
        self._transcript_sticky = False
        self.transcript.setUpdatesEnabled(False)
        self.transcript.setLayoutMode(QListView.Batched)
        self.transcript.setBatchSize(80)
        try:
            for _seq, t0, t1, zh, en in rows:
                self._add_history_row(t0, t1 or ((t0 or 0) + 3), zh, en)
            try:
                marks = self.store.conn.execute(
                    "SELECT kind, note, t_marker FROM markers WHERE session_id=?"
                    " ORDER BY t_marker", (sid,)).fetchall()
                for kind, note, t in marks:
                    self._add_history_marker(kind, note, t)
            except Exception:  # noqa: BLE001
                pass
            if getattr(self, "_filter_text", ""):
                self._apply_filter(self._filter_text)
        finally:
            self.transcript.setLayoutMode(QListView.SinglePass)
            self.transcript.setUpdatesEnabled(True)
            self._transcript_sticky = sticky
        self.transcript.scrollToTop()
        self._refresh_status()

    def _add_history_row(self, t0, t1, zh, en):
        zh, en = zh or "", en or ""
        en_s, zh_s = en.strip(), zh.strip()
        title = "\n".join(p for p in (en_s, zh_s) if p) or "（空）"
        item = QListWidgetItem(title)
        item.setData(Qt.UserRole, {
            "kind": "seg", "t0": t0, "t1": t1, "zh": zh, "en": en})
        self.transcript.addItem(item)

    def _add_history_marker(self, kind, note, t):
        icon = "⭐" if kind == "user" else "⏸"
        item = QListWidgetItem(f"{icon}  {note or ''}")
        item.setData(Qt.UserRole, {"kind": "marker", "t0": t})
        self.transcript.addItem(item)

    def _apply_filter(self, text):
        self._filter_text = text.strip().lower()
        for i in range(self.transcript.count()):
            self._filter_list_item(self.transcript.item(i))

    def _filter_list_item(self, item):
        text = getattr(self, "_filter_text", "")
        w = self.transcript.itemWidget(item)
        if isinstance(w, _SegmentCard):
            if w.partial:
                return
            self._apply_filter_to_item(item, w)
            return
        data = item.data(Qt.UserRole) or {}
        if data.get("kind") == "marker":
            return
        blob = f"{data.get('zh', '')} {data.get('en', '')} {item.text()}".lower()
        item.setHidden(bool(text) and text not in blob)

    def _apply_filter_to_item(self, item, card):
        text = getattr(self, "_filter_text", "")
        hidden = bool(text) and text not in card.zh_text.lower() and text not in card.en_text.lower()
        item.setHidden(hidden)

    def _refresh_status(self):
        n = 0
        for i in range(self.transcript.count()):
            item = self.transcript.item(i)
            w = self.transcript.itemWidget(item)
            if isinstance(w, _SegmentCard):
                if not w.partial:
                    n += 1
                continue
            data = item.data(Qt.UserRole) or {}
            if data.get("kind") != "marker":
                n += 1
        extra = " · 双击句子可回听" if n else ""
        hint = ""
        sid = self.current_session
        if sid and not self._recording_active:
            extra_names = [r[1] for r in self.store.list_session_audio(sid)]
            wav_n = wav_bytes_total(config.AUDIO_DIR, sid, extra_names)
            if wav_n >= PROMPT_MIN_BYTES:
                hint = f" · 录音 {format_bytes(wav_n)}（课节右键可压缩）"
        self.status.showMessage(f"{n} 段{extra}{hint} · 会话 {self.current_session or '—'}")

    # ---------- 回放 ----------
    def _on_card_dblclick(self, item):
        w = self.transcript.itemWidget(item)
        if isinstance(w, _SegmentCard):
            t0, t1 = w.t0, w.t1
        else:
            data = item.data(Qt.UserRole) or {}
            if data.get("kind") == "marker":
                return
            t0 = data.get("t0")
            t1 = data.get("t1") or ((t0 + 3) if t0 is not None else None)
            if t0 is None:
                return
        if not self._audio_routes:
            self.status.showMessage("本会话没有录音文件，无法回听", 3000)
            return
        self._play_range(t0, t1)

    def _bind_session_audio(self, sid: int):
        self.audio_path = resolve_audio(config.AUDIO_DIR, f"session_{sid}.wav")
        self._audio_routes = self._build_audio_routes(sid)

    def _build_audio_routes(self, sid: int):
        """构建「墙钟 → 对应录音文件」路由表 [(路径, 起始墙钟)]，按时间排序。

        segments.t_start/t_end 是墙钟 epoch 秒（_to_wall 转换）。主录音
        session_{sid}.wav（压缩后可能是 .m4a）从 sessions.started_at 起；
        续录是独立文件（session_{sid}_contN.wav），起始墙钟登记在
        session_audio 表。回听时按 t0 落到所在文件，文件内位置 =
        墙钟 - 该文件起始墙钟（连续录、暂停不暂停录音，无需扣暂停）。
        """
        sess = self.store.get_session(sid)
        if not sess:
            return []
        routes = []
        try:
            main_start = datetime.fromisoformat(sess[3]).timestamp()
        except (TypeError, ValueError):
            main_start = None
        main_path = resolve_audio(config.AUDIO_DIR, f"session_{sid}.wav")
        if main_path is not None and main_start is not None:
            routes.append((str(main_path), main_start))
        for _ord, fname, start in self.store.list_session_audio(sid):
            p = resolve_audio(config.AUDIO_DIR, fname)
            if p is not None:
                routes.append((str(p), float(start)))
        routes.sort(key=lambda r: r[1])
        return routes

    def _play_range(self, t0, t1):
        routes = getattr(self, "_audio_routes", None)
        path, p0, p1 = None, t0, t1
        if routes:
            chosen = None
            for r in routes:
                if r[1] <= t0 + 1e-6:
                    chosen = r
                else:
                    break
            if chosen is not None:
                path, start = chosen
                p0 = max(0.0, t0 - start)
                # 段落在同一段录音内；越界（跨续录边界）则钳到该 wav 末尾
                nxt = next((r[1] for r in routes if r[1] > start), t1 + 1)
                p1 = min(t1, nxt) - start
        if not path:
            self.status.showMessage("本会话没有录音文件，无法回听", 3000)
            return
        if p1 - p0 < 0.3:
            p1 = p0 + 0.3   # 至少播 0.3s，防止 t1 解析异常时秒停
        self._play_until = int(p1 * 1000)
        self._pending_pos = int(p0 * 1000)
        self.player.setSource(QUrl.fromLocalFile(path))
        # 大 wav（1 小时课 ≈ 100MB）加载需几百 ms，media 未就绪时 setPosition 无效；
        # 已加载则立即定位，否则等 _on_media_status 的 LoadedMedia 再 seek。
        if self.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia:
            self.player.setPosition(self._pending_pos)
            self._pending_pos = None
        self.player.play()

    def _on_media_status(self, status):
        if self._pending_pos is not None and status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.player.setPosition(self._pending_pos)
            self._pending_pos = None

    def _on_pos(self, pos):
        if getattr(self, "_play_until", 0) and pos >= self._play_until:
            self.player.pause()

    # ---------- 计入笔记（AI 去噪整理） / 导出 / 设置 ----------
    def on_save_note(self):
        if not self.current_session:
            return
        sess = self.store.get_session(self.current_session)
        cid = sess[1] if sess else None
        dlg = _NoteDialog(self, self.store, cid, self.current_session)
        if not dlg.exec():
            return
        course_id = dlg.result_course_id
        title = dlg.title_edit.text().strip() or "课堂实录"
        course = self.store.get_course(course_id) if course_id else None
        course_name = f"{course[1]} {course[2]}".strip() if course else "课堂实录"
        course_code = (course[1] or "").strip() if course else ""
        sid = self.current_session
        lecture_n = self.store.session_index(sid)
        self._pending_note = {
            "course_id": course_id,
            "course_name": course_name,
            "course_code": course_code,
            "title": title,
            "course": course,
            "sid": sid,
            "lecture_n": lecture_n,
        }
        self.btn_note.setEnabled(False)
        self.status.showMessage("正在整理笔记，并提取术语供确认…", 0)

        def run():
            draft = None
            note_err = None
            gloss_rows = []
            gloss_err = None

            def do_note():
                nonlocal draft, note_err
                try:
                    from app.note_agent import NoteAgent
                    from app.materials import extract_pdf_text
                    overview = slides = ""
                    cm = self.store.get_course_material(course_id)
                    if cm:
                        overview = extract_pdf_text(cm[1], max_chars=8000)
                    sm = self.store.get_session_material(sid)
                    if sm:
                        slides = extract_pdf_text(sm[1], max_chars=12000)
                    draft = NoteAgent(self.store).generate_note(
                        sid, course=course_name, title=title,
                        overview=overview, slides=slides)
                except Exception as e:  # noqa: BLE001
                    note_err = e

            def do_gloss():
                nonlocal gloss_rows, gloss_err
                if not course_id:
                    return
                try:
                    from app.glossary_extract import (
                        extract_candidates, pairs_from_segments)
                    pairs = pairs_from_segments(self.store.list_segments(sid))
                    if pairs:
                        gloss_rows = extract_candidates(
                            pairs, self.store.list_glossary(course_id))
                except Exception as e:  # noqa: BLE001
                    gloss_err = str(e)

            t_n = threading.Thread(target=do_note)
            t_g = threading.Thread(target=do_gloss)
            t_n.start()
            t_g.start()
            t_n.join()
            t_g.join()
            if note_err:
                self.note_failed.emit(str(note_err))
                return
            self._pending_note["gloss_rows"] = gloss_rows
            self._pending_note["gloss_err"] = gloss_err
            self.note_ready.emit(draft)

        threading.Thread(target=run, daemon=True).start()

    def _on_note_ready(self, draft: dict):
        self.btn_note.setEnabled(True)
        self.status.showMessage("笔记草稿已生成 · 检查后写入 Obsidian", 0)
        p = self._pending_note
        if not p:
            return
        from app.vault_notes import (inspect_concepts, meta_from_settings,
                                     render_lecture)
        meta = meta_from_settings(
            p["course_code"], p["course_name"], p["sid"], p["lecture_n"])
        if not draft.get("short_title") or draft.get("short_title") == "课堂实录":
            draft = dict(draft)
            draft["short_title"] = p["title"]
        lecture_md = render_lecture(meta, draft)
        rows = inspect_concepts(meta, draft)
        dlg = _NotePreviewDialog(self, lecture_md, rows)
        if dlg.exec():
            self._save_note(draft, dlg.result_markdown(), meta)

    def _on_note_failed(self, err: str):
        self.btn_note.setEnabled(True)
        self.status.showMessage("AI 笔记生成失败", 0)
        QMessageBox.critical(self, "笔记生成失败", err)

    def _save_note(self, draft: dict, lecture_md: str, meta):
        from app.vault_notes import write_vault
        p = self._pending_note
        existing = self.store.get_note_path(p["sid"])
        lecture_path = pathlib.Path(existing) if existing else None
        if lecture_path is not None and not lecture_path.exists():
            lecture_path = None
        try:
            result = write_vault(meta, draft, lecture_markdown=lecture_md,
                                 lecture_path=lecture_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "写入笔记失败", str(e))
            return
        self.store.set_note_path(p["sid"], str(result.lecture_path))
        if p.get("course_id"):
            title = f"第 {p['lecture_n']} 节 · {draft.get('short_title') or p['title']}"
            self.store.update_session_title(p["sid"], title)
        n_new = len(result.created_concepts)
        n_up = len(result.updated_concepts)
        n_gloss = self._confirm_glossary_rows(
            p.get("course_id"), p.get("gloss_rows") or [],
            err=p.get("gloss_err"), quiet_if_empty=True)
        gloss_line = f"术语表：写入 {n_gloss} 条\n" if n_gloss else ""
        msg = (f"课节页：{result.lecture_path}\n"
               f"概念卡：新建 {n_new} · 合并 {n_up}\n"
               f"{gloss_line}"
               f"概览：{result.moc_path}\n\n在 Obsidian 中打开课节页？")
        ret = QMessageBox.question(
            self, "已写入笔记", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ret == QMessageBox.Yes:
            subprocess.Popen(
                ["open", f"obsidian://open?path={quote(str(result.lecture_path))}"])
        self._reload_session_list(select_sid=p["sid"])

    def on_export(self):
        if not self.current_session:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 Markdown", f"session_{self.current_session}.md", "Markdown (*.md)")
        if path:
            self.store.export_markdown(self.current_session, path=path)
            self.status.showMessage(f"已导出: {path}", 5000)

    def on_settings(self):
        s = settings.load()
        old_provider = s.get("translate_provider", "deepseek")
        # 录制中不能切翻译引擎：会把 self.recorder 置空，导致无法正常结束。
        recording = bool(getattr(self, "_recording_active", False))
        dlg = _SettingsDialog(self, s, lock_provider=recording)
        if dlg.exec():
            settings.save(dlg.values())
            new_provider = dlg.values().get("translate_provider", "deepseek")
            if new_provider != old_provider:
                if recording:
                    self.status.showMessage("录制中不能切换翻译引擎，结束本次录音后生效", 5000)
                else:
                    # 翻译引擎切换：下次录制生效（重建 recorder 与翻译器）
                    self.recorder = None
                    self.tsl = make_translator(new_provider)
                    self.status.showMessage(
                        f"翻译引擎已切换为 {_PROVIDER_NAMES.get(new_provider, new_provider)}（下次录制生效）",
                        5000)

    # ---------- 课程管理（新增/重命名/删除） ----------
    def on_add_course(self):
        dlg = _CourseDialog(self, title="新增课程")
        if dlg.exec():
            code, name = dlg.values()
            if code or name:
                self.store.add_course(code, name)
                self._reload_course_list()
                self._reload_session_list()
                self.status.showMessage(f"已新增: {code} {name}".strip(), 4000)

    def _on_course_menu(self, pos):
        item = self.course_list.itemAt(pos)
        cid = item.data(Qt.UserRole) if item else None
        menu = _context_menu(self)
        act_add = menu.addAction("新增课程")
        act_overview = None
        act_overview_clear = None
        if item and cid is not None:
            mat = self.store.get_course_material(cid)
            label = ("更换课程总览课件…" if mat
                     else "上传课程总览课件…")
            if mat:
                label += f"（{mat[0]}）"
            act_overview = menu.addAction(label)
            if mat:
                act_overview_clear = menu.addAction("移除课程总览课件")
        act_gloss = menu.addAction("术语表") if item and cid is not None else None
        act_ren = menu.addAction("重命名课程") if item and cid is not None else None
        act_del = menu.addAction("删除课程") if item and cid is not None else None
        chosen = menu.exec(self.course_list.viewport().mapToGlobal(pos))
        if chosen == act_add:
            self.on_add_course()
        elif cid is not None and act_overview is not None and chosen == act_overview:
            self._attach_course_pdf(cid)
        elif cid is not None and act_overview_clear is not None and chosen == act_overview_clear:
            self._clear_course_pdf(cid)
        elif cid is not None and act_gloss is not None and chosen == act_gloss:
            self._edit_glossary(cid)
        elif cid is not None and chosen == act_ren:
            self._rename_course(cid)
        elif cid is not None and chosen == act_del:
            self._delete_course(cid)

    def _on_session_menu(self, pos):
        item = self.session_list.itemAt(pos)
        sid = item.data(Qt.UserRole) if item else None
        if sid is None:
            return
        menu = _context_menu(self)
        act_cont = menu.addAction("▶ 继续录制")
        act_cont.setEnabled(not self._recording_active)
        n_fail = len(self.store.list_failed_segments(sid))
        act_retry = menu.addAction(
            f"重补失败译文（{n_fail}）" if n_fail else "重补失败译文")
        act_retry.setEnabled(
            n_fail > 0 and not self._recording_active and not self._retrying)
        act_gloss = menu.addAction("从本课提取术语…")
        act_gloss.setEnabled(not self._recording_active and not self._extracting_gloss)
        extra_names = [r[1] for r in self.store.list_session_audio(sid)]
        wav_n = wav_bytes_total(config.AUDIO_DIR, sid, extra_names)
        act_zip = menu.addAction(
            f"压缩本节录音（{format_bytes(wav_n)}）" if wav_n else "压缩本节录音")
        act_zip.setEnabled(
            wav_n > 0 and encoder_available()
            and not self._recording_active and not self._compressing)
        menu.addSeparator()
        sm = self.store.get_session_material(sid)
        act_slides = menu.addAction(
            f"更换本节课件…（{sm[0]}）" if sm else "上传本节课件…")
        act_slides_clear = menu.addAction("移除本节课件") if sm else None
        menu.addSeparator()
        act_ren = menu.addAction("重命名课节")
        chosen = menu.exec(self.session_list.viewport().mapToGlobal(pos))
        if chosen == act_cont:
            self.session_list.setCurrentItem(item)
            self.current_session = sid
            self._bind_session_audio(sid)
            self.on_continue()
        elif chosen == act_zip:
            self._start_compress(sid)
        elif chosen == act_retry:
            self._retry_failed(sid)
        elif chosen == act_gloss:
            self._extract_glossary(sid)
        elif chosen == act_slides:
            self._attach_session_pdf(sid)
        elif act_slides_clear is not None and chosen == act_slides_clear:
            self._clear_session_pdf(sid)
        elif chosen == act_ren:
            self._rename_session(sid)

    def _session_extra_audio_names(self, sid: int) -> list:
        return [r[1] for r in self.store.list_session_audio(sid)]

    def _maybe_offer_compress(self, sid: int):
        if self._recording_active or self._compressing:
            return
        extra = self._session_extra_audio_names(sid)
        n = wav_bytes_total(config.AUDIO_DIR, sid, extra)
        if n < PROMPT_MIN_BYTES:
            return
        if not encoder_available():
            self.status.showMessage(
                f"本节录音 {format_bytes(n)}。本机没有转码工具，无法压缩", 8000)
            return
        est = format_bytes(estimate_m4a_bytes(n))
        box = QMessageBox(self)
        box.setWindowTitle("压缩录音")
        box.setText(
            f"本节录音 {format_bytes(n)}（未压缩 WAV，约 115 MB/小时）。\n"
            f"压成 AAC 后大约 {est}，双击回听仍可用。课后压缩，不影响下一堂课。")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        box.button(QMessageBox.Yes).setText("现在压缩")
        box.button(QMessageBox.No).setText("以后")
        if box.exec() == QMessageBox.Yes:
            self._start_compress(sid, ask=False)

    def _start_compress(self, sid: int, *, ask: bool = True):
        if self._recording_active or self._compressing:
            return
        extra = self._session_extra_audio_names(sid)
        n = wav_bytes_total(config.AUDIO_DIR, sid, extra)
        if n <= 0:
            self.status.showMessage("本节没有未压缩的 WAV", 3000)
            return
        if not encoder_available():
            QMessageBox.warning(
                self, "无法压缩",
                "本机没有转码工具。macOS 应自带 afconvert；也可以安装 ffmpeg 并加入 PATH。")
            return
        if ask:
            est = format_bytes(estimate_m4a_bytes(n))
            ret = QMessageBox.question(
                self, "压缩录音",
                f"把本节 {format_bytes(n)} 的 WAV 压成 AAC（大约 {est}）？\n"
                "压缩完成后删除原 WAV，双击回听仍可用。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ret != QMessageBox.Yes:
                return
        self._compressing = True
        self.status.showMessage(f"正在压缩录音（{format_bytes(n)}）…", 0)
        extra_names = list(extra)

        def run():
            err = ""
            result = {"before": 0, "after": 0, "renamed": []}
            try:
                result = compress_session(
                    config.AUDIO_DIR, sid, extra_names,
                    on_progress=self.compress_progress.emit)
                for old, new in result["renamed"]:
                    if old != f"session_{sid}.wav":
                        self.store.rename_session_audio_file(sid, old, new)
            except Exception as e:  # noqa: BLE001
                err = str(e)
            payload = {"sid": sid, "err": err, **result}
            self.compress_finished.emit(payload)

        threading.Thread(target=run, daemon=True).start()

    def _on_compress_finished(self, payload: dict):
        self._compressing = False
        sid = payload.get("sid")
        err = payload.get("err") or ""
        if err:
            QMessageBox.warning(self, "压缩未完成", err)
            if sid:
                self._bind_session_audio(sid)
            return
        before = payload.get("before") or 0
        after = payload.get("after") or 0
        if sid:
            self._bind_session_audio(sid)
        if before:
            self.status.showMessage(
                f"已压缩录音 {format_bytes(before)} → {format_bytes(after)}，回听仍可用", 8000)
        else:
            self.status.showMessage("没有需要压缩的录音", 3000)

    def _attach_course_pdf(self, cid: int):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择课程总览课件（PDF）", "", "PDF (*.pdf)")
        if not path:
            return
        dest = config.MATERIALS_DIR / f"course_{cid}.pdf"
        from app.materials import save_pdf
        save_pdf(path, dest)
        name = pathlib.Path(path).name
        self.store.set_course_material(cid, name, str(dest))
        self.status.showMessage(f"已保存课程总览课件：{name}", 4000)

    def _clear_course_pdf(self, cid: int):
        mat = self.store.get_course_material(cid)
        self.store.clear_course_material(cid)
        if mat:
            p = pathlib.Path(mat[1])
            if p.exists():
                p.unlink()
        self.status.showMessage("已移除课程总览课件", 3000)

    def _attach_session_pdf(self, sid: int):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择本节课件（PDF）", "", "PDF (*.pdf)")
        if not path:
            return
        dest = config.MATERIALS_DIR / f"session_{sid}.pdf"
        from app.materials import save_pdf
        save_pdf(path, dest)
        name = pathlib.Path(path).name
        self.store.set_session_material(sid, name, str(dest))
        self.status.showMessage(f"已保存本节课件：{name}", 4000)

    def _clear_session_pdf(self, sid: int):
        mat = self.store.get_session_material(sid)
        self.store.clear_session_material(sid)
        if mat:
            p = pathlib.Path(mat[1])
            if p.exists():
                p.unlink()
        self.status.showMessage("已移除本节课件", 3000)

    def _rename_session(self, sid):
        sess = self.store.get_session(sid)
        title, ok = QInputDialog.getText(
            self, "重命名课节", "课节标题（如「第 1 节 · 神经网络基础」）：",
            text=sess[2] if sess else "课堂实录")
        if ok and title.strip():
            self.store.update_session_title(sid, title.strip())
            self._reload_session_list(select_sid=sid)
            self.status.showMessage("课节已重命名", 3000)

    def _rename_course(self, cid):
        course = self.store.get_course(cid)
        if not course:
            return
        dlg = _CourseDialog(self, title="重命名课程", code=course[1], name=course[2])
        if dlg.exec():
            code, name = dlg.values()
            self.store.rename_course(cid, code, name)
            self._reload_course_list()
            self._reload_session_list()
            self.status.showMessage("课程已更新", 3000)

    def _delete_course(self, cid):
        course = self.store.get_course(cid)
        if not course:
            return
        ret = QMessageBox.question(
            self, "删除课程",
            f"删除「{course[1]} {course[2]}」？\n其下录音会保留但归入「未分类」。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.store.delete_course(cid)
            if self._cur_course_id == cid:
                self._cur_course_id = None
            self._reload_course_list()
            self._reload_session_list()
            if self.course_list.count() > 0 and self._cur_course_id is None:
                self.course_list.setCurrentRow(0)
                self._on_course_click(self.course_list.item(0))
            self.status.showMessage("课程已删除（录音保留在未分类）", 4000)

    def _edit_glossary(self, cid):
        course = self.store.get_course(cid)
        if not course:
            return
        label = f"{course[1]} {course[2]}".strip()
        text = format_glossary_text(self.store.list_glossary(cid))
        dlg = _GlossaryDialog(self, label, text)
        if dlg.exec():
            terms = parse_glossary_text(dlg.result_text())
            self.store.replace_glossary(cid, terms)
            if hasattr(self.tsl, "set_glossary"):
                self.tsl.set_glossary(terms)
            self.status.showMessage(f"术语表已保存（{len(terms)} 条）", 4000)

    def _retry_failed(self, sid):
        if self._retrying or self._recording_active:
            return
        rows = self.store.list_failed_segments(sid)
        if not rows:
            self.status.showMessage("没有翻译失败的句子", 3000)
            return
        self._retrying = True
        self.status.showMessage(f"正在重补 {len(rows)} 句译文…", 0)
        sess = self.store.get_session(sid)
        cid = sess[1] if sess else None
        terms = self.store.list_glossary(cid) if cid else []
        tsl = self.tsl
        if hasattr(tsl, "set_glossary"):
            tsl.set_glossary(terms)
        store = self.store

        def run():
            n_ok = 0
            err = ""
            try:
                for seq, _t0, _t1, en, _old in rows:
                    if not en or en.startswith("[ASR错误]"):
                        continue
                    ctx = store.recent_context(sid, seq, n=config.TRANSLATE_CONTEXT)
                    zh = translate_with_retry(tsl, en, context=ctx or None)
                    store.update_segment_zh(sid, seq, zh)
                    if not zh.startswith("[翻译失败]"):
                        n_ok += 1
            except Exception as e:  # noqa: BLE001
                err = str(e)
            self.retry_finished.emit(sid, n_ok, err)

        threading.Thread(target=run, daemon=True).start()

    def _on_retry_finished(self, sid, n_ok, err):
        self._retrying = False
        if err:
            QMessageBox.critical(self, "重补失败", err)
            return
        left = len(self.store.list_failed_segments(sid))
        msg = f"已重补 {n_ok} 句"
        if left:
            msg += f"，仍有 {left} 句失败"
        self.status.showMessage(msg, 5000)
        if self.current_session == sid:
            self._load_session(sid)

    def _extract_glossary(self, sid):
        if self._extracting_gloss or self._recording_active:
            return
        sess = self.store.get_session(sid)
        cid = sess[1] if sess else None
        if not cid:
            QMessageBox.information(
                self, "提取术语", "请先把这节课归入一门课程（术语表按课程累积）。")
            return
        from app.glossary_extract import pairs_from_segments
        pairs = pairs_from_segments(self.store.list_segments(sid))
        if not pairs:
            QMessageBox.information(
                self, "提取术语",
                "这节没有可用的英中对照。\n请先上完课或重补失败译文。")
            return
        self._extracting_gloss = True
        self.status.showMessage("正在从本课译文提取术语（需确认后才写入）…", 0)
        existing = self.store.list_glossary(cid)

        def run():
            try:
                from app.glossary_extract import extract_candidates
                rows = extract_candidates(pairs, existing)
                self.gloss_ready.emit({"cid": cid, "sid": sid, "rows": rows})
            except Exception as e:  # noqa: BLE001
                self.gloss_failed.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_gloss_failed(self, err: str):
        self._extracting_gloss = False
        self.status.showMessage("术语提取失败", 0)
        QMessageBox.critical(self, "提取术语失败", err)

    def _on_gloss_ready(self, payload: dict):
        self._extracting_gloss = False
        self.status.showMessage("术语候选已生成 · 勾选后写入", 0)
        n = self._confirm_glossary_rows(
            payload.get("cid"), payload.get("rows") or [])
        if n:
            self.status.showMessage(f"已写入术语表 {n} 条", 5000)

    def _confirm_glossary_rows(self, cid, rows, *, err=None, quiet_if_empty=False) -> int:
        """弹出确认框；返回实际写入条数。未勾选或取消返回 0。"""
        if not cid:
            return 0
        if err:
            if not quiet_if_empty:
                QMessageBox.warning(self, "提取术语失败", err)
            else:
                self.status.showMessage(f"术语提取失败：{err}", 8000)
            return 0
        pending = [r for r in (rows or []) if r.get("action") != "已有"]
        skipped = sum(1 for r in (rows or []) if r.get("action") == "已有")
        if not pending:
            if not quiet_if_empty:
                extra = f"另有 {skipped} 条已在术语表中。" if skipped else ""
                QMessageBox.information(self, "确认术语表", "没有新的术语可添加。" + extra)
            return 0
        dlg = _GlossaryExtractDialog(self, pending, skipped)
        if not dlg.exec():
            return 0
        chosen = dlg.selected_terms()
        if not chosen:
            if not quiet_if_empty:
                self.status.showMessage("未选择任何术语", 3000)
            return 0
        self.store.upsert_glossary_terms(cid, chosen)
        if hasattr(self.tsl, "set_glossary"):
            self.tsl.set_glossary(self.store.list_glossary(cid))
        return len(chosen)


class _NotePreviewDialog(QDialog):
    """预览课节正文 + 将新建/合并的概念卡清单，确认后写入 vault。"""

    def __init__(self, parent, lecture_md: str, concept_rows: list):
        super().__init__(parent)
        self.setWindowTitle("计入笔记 · 预览")
        self.resize(760, 640)
        lay = QVBoxLayout(self)
        n_new = sum(1 for r in concept_rows if r.get("action") == "新建")
        n_up = sum(1 for r in concept_rows if r.get("action") == "合并")
        tip = QLabel(
            f"上：课节页（可改）。下：将写入概念卡（新建 {n_new} · 合并 {n_up}）。"
            "确认写入后，会再请你勾选本课术语是否进入术语表。")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        from PySide6.QtWidgets import QPlainTextEdit
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(lecture_md)
        lay.addWidget(self.editor, 3)
        cards = QPlainTextEdit()
        cards.setReadOnly(True)
        lines = []
        for r in concept_rows:
            extra = f"  {r.get('en')}" if r.get("en") else ""
            one = r.get("one_liner") or ""
            lines.append(f"[{r.get('action')}] {r.get('name')}{extra}")
            if one:
                lines.append(f"    {one}")
        cards.setPlainText("\n".join(lines) if lines else "（本课没有概念卡）")
        cards.setFixedHeight(140)
        lay.addWidget(cards, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def result_markdown(self) -> str:
        return self.editor.toPlainText().strip()

    def result_text(self) -> str:
        return self.result_markdown()


class _CourseDialog(QDialog):
    """新增/重命名课程：代码 + 名称。"""

    def __init__(self, parent, title="新增课程", code="", name=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("课程代码（如 EF5560，可留空）"))
        self.code_edit = QLineEdit(code)
        lay.addWidget(self.code_edit)
        lay.addWidget(QLabel("课程/分类名称（会议、访谈等也可）"))
        self.name_edit = QLineEdit(name)
        lay.addWidget(self.name_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self):
        return self.code_edit.text().strip(), self.name_edit.text().strip()


class _GlossaryDialog(QDialog):
    """课程术语表：每行 English = 中文。"""

    def __init__(self, parent, course_label: str, text: str):
        super().__init__(parent)
        self.setWindowTitle(f"术语表 · {course_label}")
        self.resize(480, 420)
        lay = QVBoxLayout(self)
        tip = QLabel(
            "每行一条：English = 中文。上课翻译按此用词；"
            "英文名也会喂给识别，减少人名/课名听错。\n"
            "仅 DeepSeek / 百炼 / Ollama 会把术语写进翻译提示；机器翻译引擎无效。\n"
            "也可在课节上右键「从本课提取术语」，确认后再写入。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #5A5F66; font-size: 12px;")
        lay.addWidget(tip)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(
            "# 例：\nJohns Hopkins = 约翰·霍普金斯\n"
            "data visualization = 数据可视化")
        self.edit.setPlainText(text)
        lay.addWidget(self.edit)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def result_text(self) -> str:
        return self.edit.toPlainText()


class _GlossaryExtractDialog(QDialog):
    """课后术语候选：勾选后才写入课程术语表。"""

    def __init__(self, parent, rows: list, skipped: int = 0):
        super().__init__(parent)
        self.setWindowTitle("确认写入术语表")
        self.resize(520, 440)
        self._rows = rows
        lay = QVBoxLayout(self)
        n_new = sum(1 for r in rows if r.get("action") == "新建")
        n_chg = sum(1 for r in rows if r.get("action") == "改译")
        extra = f"已跳过 {skipped} 条已在表中。" if skipped else ""
        tip = QLabel(
            f"DeepSeek 根据本课英中对照提出候选，请勾选要写入术语表的条目。\n"
            f"不勾选或取消则不改术语表。新建 {n_new} · 改译 {n_chg}"
            f"（改译默认不勾，避免覆盖已定译名）。{extra}")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.list = QListWidget()
        for r in rows:
            if r.get("action") == "改译":
                label = f"[改译] {r['en']}  {r.get('old_zh')} → {r['zh']}"
                checked = False
            else:
                why = f"  · {r['reason']}" if r.get("reason") else ""
                label = f"[新建] {r['en']} = {r['zh']}{why}"
                checked = True
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            item.setData(Qt.UserRole, (r["en"], r["zh"]))
            self.list.addItem(item)
        lay.addWidget(self.list)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("写入所选")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def selected_terms(self) -> list[tuple[str, str]]:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out


class _NoteDialog(QDialog):
    def __init__(self, parent, store: Store, course_id, sid):
        super().__init__(parent)
        self.setWindowTitle("计入笔记")
        self.store = store
        self.result_course_id = course_id
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("目标课程"))
        self.course_combo = QComboBox()
        self.course_combo.addItem("（不关联课程）", None)
        self.idx_map = {}
        for i, (cid, code, name) in enumerate(store.list_courses(), start=1):
            self.course_combo.addItem(f"{code} {name}".strip(), cid)
            self.idx_map[cid] = i
        if course_id in self.idx_map:
            self.course_combo.setCurrentIndex(self.idx_map[course_id])
        lay.addWidget(self.course_combo)
        lay.addWidget(QLabel("课节短标题（文件名用「第 N 节-短标题」；也可让 Agent 根据内容命名）"))
        sess = store.get_session(sid) if sid else None
        default = (sess[2] if sess and sess[2] else "课堂实录")
        self.title_edit = QLineEdit(default)
        lay.addWidget(self.title_edit)
        bits = []
        if course_id:
            cm = store.get_course_material(course_id)
            if cm:
                bits.append(f"课程总览：{cm[0]}")
        if sid:
            sm = store.get_session_material(sid)
            if sm:
                bits.append(f"本节课件：{sm[0]}")
        hint = QLabel(
            "计入时会带上：\n" + "\n".join(bits)
            if bits else
            "尚未上传课件。可在左侧课程 / 课节上右键上传 PDF（总览 + 本节），笔记会补结构。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8A9099; font-size: 12px;")
        lay.addWidget(hint)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def accept(self):
        self.result_course_id = self.course_combo.currentData()
        super().accept()


class _SettingsDialog(QDialog):
    def __init__(self, parent, s: dict, lock_provider: bool = False):
        super().__init__(parent)
        self.setWindowTitle("设置")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Obsidian vault 路径（计入笔记的目标）"))
        row = QHBoxLayout()
        self.vault_edit = QLineEdit(s.get("vault", ""))
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.vault_edit)
        row.addWidget(browse)
        lay.addLayout(row)
        lay.addWidget(QLabel("课节笔记子目录（vault 下，将再分课堂-{代码}/）"))
        self.sub_edit = QLineEdit(s.get("notes_subdir", "01-章节笔记"))
        lay.addWidget(self.sub_edit)
        lay.addWidget(QLabel("概念卡片子目录（跨课累积）"))
        self.concepts_edit = QLineEdit(s.get("concepts_subdir", "02-概念卡片"))
        lay.addWidget(self.concepts_edit)
        lay.addWidget(QLabel("翻译引擎（实时字幕翻译）"))
        self.provider_combo = QComboBox()
        cur = s.get("translate_provider", "deepseek")
        for idx, (key, label) in enumerate(_PROVIDER_NAMES.items()):
            self.provider_combo.addItem(label, key)
            if key == cur:
                self.provider_combo.setCurrentIndex(idx)
        if lock_provider:
            # 录制中锁定翻译引擎（切换会置空 recorder → 录音无法结束）
            self.provider_combo.setEnabled(False)
            self.provider_combo.setToolTip("录制中不可切换，结束本次录音后生效")
        lay.addWidget(self.provider_combo)
        if lock_provider:
            lock_tip = QLabel("⏺ 录制中：翻译引擎已锁定，结束录音后可切换。")
            lock_tip.setStyleSheet("color: #E5484D; font-size: 11px;")
            lay.addWidget(lock_tip)
        lay.addWidget(QLabel("识别模式（识别精度 vs 字幕延迟）"))
        self.asr_combo = QComboBox()
        for idx, (key, label) in enumerate(_ASR_MODES.items()):
            self.asr_combo.addItem(label, key)
            if key == s.get("asr_mode", "realtime"):
                self.asr_combo.setCurrentIndex(idx)
        lay.addWidget(self.asr_combo)
        asr_tip = QLabel(
            "字幕（悬浮）：始终用轻量模型短窗跟读，尽量快。\n"
            "框内（英文/中文积累）：句子定稿后用大模型精修再翻译，可慢但更准。\n"
            "「精准模式」只加长框内定稿窗口并过滤环境音，字幕仍走短窗草稿。")
        asr_tip.setWordWrap(True)
        asr_tip.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(asr_tip)
        tip = QLabel(
            "上课建议 DeepSeek：课堂中文最顺，并吃术语表和上下文。\n"
            "百炼 Qwen：也吃术语表，常有免费额度；质量通常不如 DeepSeek 稳。\n"
            "Ollama：可断网、吃术语表；要自己起服务，Mac 上往往偏慢。\n"
            "百度 / 阿里机器翻译：快、有免费额度，但不吃术语表，课名/人名易乱译。\n"
            "腾讯：当前待修，课上不要选。\n"
            "笔记整理始终走 DeepSeek，和这里无关。术语表在课程上右键。\n"
            "其它引擎的 Key 写在项目 .env（参照 .env.example）。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: gray; font-size: 11px;")
        lay.addWidget(tip)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        p = QFileDialog.getExistingDirectory(self, "选择 Obsidian vault 目录")
        if p:
            self.vault_edit.setText(p)

    def values(self):
        return {"vault": self.vault_edit.text().strip(),
                "notes_subdir": self.sub_edit.text().strip() or "01-章节笔记",
                "concepts_subdir": self.concepts_edit.text().strip() or "02-概念卡片",
                "translate_provider": self.provider_combo.currentData() or "deepseek",
                "asr_mode": self.asr_combo.currentData() or "realtime"}


def _fmt_dur(sec: float) -> str:
    """秒 → mm:ss（超过 1 小时 → h:mm:ss）。"""
    s = int(sec)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


class _SessionRow(QWidget):
    """课节列表行：第 N 节 + 时间 + 时长 + 段数；录制中态红色高亮。

    让「第一节课 / 第二节课」一眼可分辨（Apple Podcasts 节目→单集的递进结构）。
    """

    def __init__(self, idx: int, started: str, dur: float, nseg: int, status: str):
        super().__init__()
        rec = status == "recording"
        md_hm = (f"{started[5:10]} {started[11:16]}"
                 if len(started) >= 16 else (started[:10] or ""))
        meta = f"{md_hm} · {_fmt_dur(dur)} · {nseg} 段"

        title = QLabel(f"第 {idx} 节" if not rec else f"● 录制中 · 第 {idx} 节")
        title.setStyleSheet(
            ("color: #E5484D; font-size: 13px; font-weight: 700; background: transparent;"
             if rec else
             "color: #1F2329; font-size: 13px; font-weight: 600; background: transparent;"))

        info = QLabel(meta)
        info.setStyleSheet("color: #8A9099; font-size: 11px; background: transparent;")

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 5, 8, 5)
        v.setSpacing(1)
        v.addWidget(title)
        v.addWidget(info)


class _SegmentCard(QWidget):
    """单条转写卡片：中文（主）+ 英文（次）+ 回听。不显示墙上时钟（对复习无用且长课加载贵）。"""

    play_clicked = Signal()

    def __init__(self, t0, t1, zh, en, partial=False):
        super().__init__()
        self.t0, self.t1 = t0, t1
        self.partial = partial
        self.zh_text = zh or ""
        self.en_text = en or ""

        frame = QFrame()
        frame.setObjectName("segPartial" if partial else "segCard")

        self.play_btn = QPushButton("▶ 回听")
        self.play_btn.setFixedHeight(22)
        self.play_btn.setStyleSheet(
            "QPushButton { background: #EEF1FB; color: #4F6BED; border: none;"
            "border-radius: 11px; font-size: 11px; padding: 0 10px; }"
            "QPushButton:hover { background: #DEE5FA; }")
        self.play_btn.clicked.connect(self.play_clicked.emit)

        self.zh = QLabel(self.zh_text)
        self.zh.setWordWrap(True)
        zh_style = ("color: #8A9099; font-size: 13px; font-style: italic; background: transparent;"
                    if partial else
                    "color: #1F2329; font-size: 14.5px; font-weight: 600; background: transparent;")
        self.zh.setStyleSheet(zh_style)
        self._zh_style_normal = self.zh.styleSheet()

        self.en = QLabel(self.en_text)
        self.en.setWordWrap(True)
        self.en.setStyleSheet(
            ("color: #B0B5BC; font-size: 11.5px; font-style: italic; background: transparent;"
             if partial else
             "color: #6A7078; font-size: 12px; background: transparent;"))

        fl = QVBoxLayout(frame)
        fl.setContentsMargins(10, 7, 10, 8)
        fl.setSpacing(3)
        if partial:
            # 草稿：只显示英文跟读，不占回听行
            self.play_btn.setVisible(False)
            self.zh.setVisible(False)
            fl.addWidget(self.en)
        else:
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(8)
            self.zh.setVisible(bool(self.zh_text))
            head.addWidget(self.zh, 1)
            head.addWidget(self.play_btn, 0, Qt.AlignTop)
            fl.addLayout(head)
            if self.en_text:
                fl.addWidget(self.en)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.addWidget(frame)
        self._frame = frame
        self._apply_frame_style()

    def _apply_frame_style(self):
        if self.partial:
            self._frame.setStyleSheet(
                "QFrame#segPartial { background: #FBFBFC; border: 1px dashed #D8DBE0;"
                "border-radius: 8px; }")
        else:
            self._frame.setStyleSheet(
                "QFrame#segCard { background: white; border: 1px solid #E7E9ED;"
                "border-radius: 8px; }"
                "QFrame#segCard:hover { border-color: #C3CDF5; }")

    def set_text(self, zh, en):
        self.zh_text = zh or ""
        self.en_text = en or ""
        self.zh.setText(self.zh_text)
        self.zh.setVisible(bool(self.zh_text))
        self.en.setText(self.en_text)
        self.en.setVisible(bool(self.en_text) or self.partial)

    def frame_height_for(self, width: int) -> int:
        h = self._frame.heightForWidth(max(width - 8, 100))
        return (h + 8) if h > 0 else -1

    def sizeHint(self):
        self._frame.adjustSize()
        h = self._frame.sizeHint().height() + 4
        from PySide6.QtCore import QSize
        return QSize(100, max(h, 46))


class _FullRow(QFrame):
    """全文记录的单行：时间戳 + 按语言显示的正文。"""

    def __init__(self, ts, en, zh, kind, note=""):
        super().__init__()
        self.kind = kind
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 5, 10, 6)
        v.setSpacing(1)
        if kind == "marker":
            lbl = QLabel(note or "")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                "color: #B8860B; background: #FFF7E6; border: 1px solid #F0DFB8;"
                "border-radius: 6px; padding: 3px 10px; font-size: 12px;")
            v.addWidget(lbl)
            self._labels = [lbl]
            self.en_lbl = self.zh_lbl = None
            self.setStyleSheet(
                "QFrame { background: transparent; border: none; }")
            return
        italic = "font-style: italic; color: #8A9099;" if kind == "partial" else ""
        self.zh_lbl = QLabel(zh or "")
        self.zh_lbl.setWordWrap(True)
        self.zh_lbl.setStyleSheet(
            f"color: #1F2329; font-size: 13.5px; font-weight: 600; background: transparent;{italic}")
        self._has_zh = bool(zh)
        self.zh_lbl.setVisible(bool(zh))  # 草稿无中文时不留空行
        self.en_lbl = QLabel(en or "")
        self.en_lbl.setWordWrap(True)
        self.en_lbl.setStyleSheet(
            f"color: #6A7078; font-size: 12px; background: transparent;{italic}")
        v.addWidget(self.zh_lbl)
        v.addWidget(self.en_lbl)
        self._labels = [self.zh_lbl, self.en_lbl]
        if kind == "partial":
            self.setStyleSheet(
                "QFrame { background: #FBFBFC; border: 1px dashed #D8DBE0; border-radius: 8px; }")
        else:
            self.setStyleSheet(
                "QFrame { background: white; border: 1px solid #E7E9ED; border-radius: 8px; }")

    def set_lang(self, lang):
        if self.kind == "marker":
            return
        show_zh = lang in ("dual", "zh")
        show_en = lang in ("dual", "en")
        self.zh_lbl.setVisible(show_zh and self._has_zh)
        self.en_lbl.setVisible(show_en)

    def height_for(self, w: int) -> int:
        self.setFixedWidth(w)
        self.adjustSize()
        return self.sizeHint().height()


class _TranscriptDialog(QDialog):
    """全文记录窗口：从头到尾完整转写，可切换 双语/中文/English。

    录制中实时追加；用户回看（向上滚动）时不被新内容拉回底部。
    """

    _LANG_LABELS = [("dual", "双语"), ("zh", "中文"), ("en", "English")]

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("全文记录")
        self.resize(760, 640)
        self._data = []          # (kind, ts, en, zh, note)
        self._last_seq = 0
        self._at_bottom = True

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        self.info = QLabel("")
        self.info.setStyleSheet("color: #8A9099; font-size: 11px;")
        self.lang_combo = QComboBox()
        for key, label in self._LANG_LABELS:
            self.lang_combo.addItem(label, key)
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.currentIndexChanged.connect(self._rebuild)
        head.addWidget(self.info)
        head.addStretch(1)
        head.addWidget(QLabel("显示"))
        head.addWidget(self.lang_combo)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.setSpacing(1)
        self.list.setWordWrap(False)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setStyleSheet(
            "QListWidget { background: #F4F5F7; border: 1px solid #E3E5E9;"
            "border-radius: 8px; padding: 6px; }"
            "QListWidget::item { padding: 4px 8px; }"
            "QListWidget::item:selected { background: #E7EDFD; color: #1F2329; }")
        self.list.verticalScrollBar().valueChanged.connect(self._on_scroll)
        lay.addWidget(self.list)

        tip = QLabel("双击任意一行可回听原音（会话有录音时）")
        tip.setStyleSheet("color: #A8ACB3; font-size: 11px;")
        lay.addWidget(tip)
        self.list.itemDoubleClicked.connect(self._on_dblclick)

    # ---------- 数据 ----------
    def reset(self):
        self._data.clear()
        self._last_seq = 0
        self._rebuild()

    def set_info(self, text: str):
        self.info.setText(text)

    def load_session(self, sid: int):
        store = self.parent().store
        self._data.clear()
        self._last_seq = 0
        rows = store.conn.execute(
            "SELECT seq, t_start, t_end, translated_text, raw_text FROM segments"
            " WHERE session_id=? ORDER BY seq", (sid,)).fetchall()
        for seq, t0, _t1, zh, en in rows:
            if not (en or zh):
                continue
            ts = time.strftime("%H:%M:%S", time.localtime(t0)) if t0 else "--:--:--"
            self._data.append(("seg", ts, en or "", zh or "", "", t0))
            self._last_seq = max(self._last_seq, seq or 0)
        try:
            for t, kind, note in store.list_markers(sid):
                ts = time.strftime("%H:%M:%S", time.localtime(t))
                icon = "⭐" if kind == "user" else "⏸"
                self._data.append(("marker", ts, "", "", f"{icon} {note or '重点/疑问'}", t))
        except Exception:  # noqa: BLE001
            pass
        n = sum(1 for d in self._data if d[0] == "seg")
        self.set_info(f"{n} 段 · {self.parent()._course_label()}")
        self._rebuild()

    def add(self, kind, seq, t0, zh, en, note=""):
        if kind == "seg":
            if seq <= self._last_seq:
                return
            self._last_seq = seq
        self._drop_partial()
        ts = time.strftime("%H:%M:%S", time.localtime(t0)) if t0 else "--:--:--"
        self._data.append((kind, ts, en, zh, note, t0))
        self._append_row(self._data[-1])
        self._stick()

    def _drop_partial(self):
        for i, d in enumerate(self._data):
            if d[0] == "partial":
                del self._data[i]
                break
        for i in range(self.list.count()):
            d = self.list.item(i).data(Qt.UserRole)
            if d and d[0] == "partial":
                self.list.takeItem(i)
                break

    # ---------- 渲染 ----------
    def _rebuild(self):
        self.list.setUpdatesEnabled(False)
        self.list.setLayoutMode(QListView.Batched)
        self.list.setBatchSize(80)
        self.list.clear()
        try:
            for d in self._data:
                self._append_row(d)
        finally:
            self.list.setLayoutMode(QListView.SinglePass)
            self.list.setUpdatesEnabled(True)
        self._stick()

    def _append_row(self, d):
        kind, ts, en, zh, note, _t0 = d
        lang = self.lang_combo.currentData() or "dual"
        if kind == "marker":
            text = note or ""
        elif kind == "partial":
            text = f"{ts}  {en or zh or ''}".strip()
        else:
            parts = []
            if lang in ("dual", "zh") and zh:
                parts.append(zh)
            if lang in ("dual", "en") and en:
                parts.append(en)
            body = "  |  ".join(parts) if parts else (zh or en or "")
            text = f"{ts}  {body}".strip()
        it = QListWidgetItem(text)
        it.setData(Qt.UserRole, d)
        if kind == "seg" and en and zh and lang == "zh":
            it.setToolTip(en)
        elif kind == "seg" and en and zh and lang == "en":
            it.setToolTip(zh)
        self.list.addItem(it)

    def _stick(self):
        if self._at_bottom:
            self.list.scrollToBottom()

    def _on_scroll(self, v):
        sb = self.list.verticalScrollBar()
        self._at_bottom = sb.maximum() - v < 24

    def _on_dblclick(self, item):
        d = item.data(Qt.UserRole)
        if not d or d[0] != "seg":
            return
        t0 = d[-1]
        if t0 is None:
            return
        win = self.parent()
        if not getattr(win, "_audio_routes", None):
            win.status.showMessage("本会话没有录音文件，无法回听", 3000)
            return
        win._play_range(t0, t0 + 3)
        win.status.showMessage("▶ 回听中…（该段 3 秒）", 2000)
