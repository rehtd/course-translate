"""底部电影式字幕（点击穿透）+ 右下角控制条（可交互）。

- SubtitleBar：锚定屏幕底部，居中大字白色文本 + 阴影，电影字幕观感；
  整窗点击穿透（WA_TransparentForMouseEvents），绝不阻挡鼠标操作。
- ControlChip：右下角小型控制条，可交互：⏸/▶ 暂停继续、★ 打点、⏹ 结束。
  快捷键（点一下控制条获得焦点后）：空格=暂停/继续，M=打点，Esc=结束。
"""
from difflib import SequenceMatcher
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

_BTN_STYLE = ("background: rgba(255,255,255,225); color: #111; border-radius: 6px;"
              "border: none; font-size: 11px;")
_STOP_STYLE = ("background: rgba(220,60,60,215); color: white; border-radius: 6px;"
               "border: none; font-size: 11px;")

# 字幕窗固定高度：上边距 12 + 英文行 38 + 下边距 16 = 66。
# 高度固定、只显示英文单行，文字长短不会把窗口撑跳。
_H_ONE = 66


def _tail_clause(text: str, max_chars: int = 72) -> str:
    """字幕短句化：只取文本最后一个句子/从句（含正在说的片段）。

    悬浮字幕 = 实时跟读提示，老师说多长都只显示最近一句；完整内容在
    主窗口转写区 / 右侧中文译文区。
    先按 .!? 断句取尾句，尾句仍超长再按 ,; 收窄到最后一个从句，
    再超则取最后 max_chars 个字符窗口（按词边界切齐，保留正在说的末尾）。
    """
    text = (text or "").strip()
    if not text:
        return ""
    tail = re.split(r"(?<=[.!?])\s+", text)[-1]
    if len(tail) > max_chars:
        tail = re.split(r"(?<=[,;])\s+", tail)[-1]
    if len(tail) > max_chars:
        # 保留末尾窗口（显示正在说的部分）：从最后 max_chars 字符处
        # 对齐到其后第一个词边界，避免从词中间切开。
        start = max(0, len(tail) - max_chars)
        cut = tail.find(" ", start)
        tail = tail[cut + 1:] if cut > 0 else tail[start:]
    return tail


def _shadow(widget, blur: int, offset: int = 2):
    e = QGraphicsDropShadowEffect(widget)
    e.setBlurRadius(blur)
    e.setOffset(0, offset)
    e.setColor(QColor(0, 0, 0, 220))
    widget.setGraphicsEffect(e)


def _apply_native_level(widget: QWidget):
    """用 pyobjc 提升窗口到浮动层级。

    切到后台或正在激活时不要碰 NSWindow：此时调 winId()/setLevel_
    会和 Cocoa 窗口激活抢主线程，表现为切回前台卡死。
    """
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None and app.applicationState() != Qt.ApplicationActive:
            return
        import ctypes
        from AppKit import NSFloatingWindowLevel
        import objc
        if not widget.isVisible():
            return
        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(widget.winId())))
        w = view.window()
        if w is None:
            return
        # 已经在浮动层就别反复 setLevel（每 3s 定时器 + 切前台都会走到这里）
        try:
            if int(w.level()) == int(NSFloatingWindowLevel):
                return
        except Exception:  # noqa: BLE001
            pass
        w.setLevel_(NSFloatingWindowLevel)   # 3：浮动层，高于普通窗口
        w.setCollectionBehavior_(1 | 256)    # 所有桌面 + 全屏辅助
    except Exception as e:  # noqa: BLE001
        print(f"[overlay] 浮动层级设置失败: {e}", flush=True)


def make_floating(widget: QWidget):
    """macOS：把字幕/控制条窗口提升到浮动层级，切换应用后仍保持可见。

    用 pyobjc（安全桥接）设置 NSWindow level；每 3 秒复查一次，
    防止 Qt/系统在应用切换时重置层级。
    """
    widget.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
    _apply_native_level(widget)
    if getattr(widget, "_float_timer", None) is None:
        timer = QTimer(widget)
        timer.timeout.connect(lambda: _apply_native_level(widget))
        timer.start(3000)
        widget._float_timer = timer


class SubtitleBar(QWidget):
    """底部电影式字幕层：只显示，点击穿透。"""

    def __init__(self, margin_bottom: int = 40, max_width: int = 1200):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 关键：点击穿透
        self.setFocusPolicy(Qt.NoFocus)

        # 英文单行。中英对照在主窗口两个积累框里看；悬浮只跟读最近一句。
        # 关闭换行，超长省略，窗口总高固定为 _H_ONE。
        self.en = QLabel("")
        self.en.setFont(QFont("Helvetica Neue", 28, QFont.Bold))
        self.en.setAlignment(Qt.AlignCenter)
        self.en.setWordWrap(False)
        self.en.setFixedHeight(38)
        self.en.setStyleSheet("color: white; background: transparent;")
        _shadow(self.en, 8)

        lay = QVBoxLayout(self)
        lay.addWidget(self.en)
        lay.setContentsMargins(24, 12, 24, 16)   # 上下留足空间，阴影不裁切
        lay.setSpacing(0)

        self.max_width = max_width
        self.margin_bottom = margin_bottom
        self._acc_en = ""   # 句子累积显示（打字机）
        self._raw_en = ""   # 未 elide 的原文（resize 时重新省略）
        self._anchor()

    def _fit(self, widget: QLabel, text: str) -> str:
        """单行省略：超出 label 宽度的文本以 … 结尾（防溢出破坏布局）。"""
        fm = QFontMetrics(widget.font())
        return fm.elidedText(text or "", Qt.ElideRight, widget.width() - 8)

    def _set_en(self, text: str):
        self._raw_en = text or ""
        self.en.setText(self._fit(self.en, self._raw_en))

    def _relayout(self):
        """固定高度布局：窗口高度恒定，文本长短不改变窗口大小。

        「字幕稳定不跳」的核心——高度固定、锚点固定，文字变化不会引起
        字幕条位置与尺寸跳动。
        """
        self.setFixedHeight(_H_ONE)
        self._anchor()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._raw_en:
            self.en.setText(self._fit(self.en, self._raw_en))

    def _anchor(self):
        scr = QGuiApplication.primaryScreen()
        if not scr:
            return
        geo = scr.availableGeometry()
        w = min(self.max_width, geo.width() - 120)
        self.setFixedWidth(w)
        self.adjustSize()
        self.move(geo.x() + (geo.width() - self.width()) // 2,
                  geo.y() + geo.height() - self.height() - self.margin_bottom)

    def update_text(self, en: str, zh: str):
        """状态/占位（启动「等待老师讲课…」、单元测试）。

        上课时悬浮字幕只走 update_partial（small 短窗，快）。
        定稿精修写入主窗口右侧框，不再回写字幕（避免晚到的准句把正在跟读的下一句拽回去）。
        """
        if not (en or "").strip():
            self._acc_en = ""
            self._set_en(zh or "")
            QTimer.singleShot(0, self._relayout)
            return
        self._acc_en = en or ""
        # 上限适配 1200px 窗口单行宽度（28px 粗体 ≈60 字符）
        self._set_en(_tail_clause(en or "", max_chars=56))
        QTimer.singleShot(0, self._relayout)

    @staticmethod
    def _accumulate(old: str, new: str, match_ratio: float = 0.5):
        """句子累积核心：返回应显示的新文本，None 表示无需刷新。

        - new 以 old 开头（打字机正常增长）→ 返回 new
        - new 与 old 有 >=match_ratio 的字符重合（5s 窗口滑头：new = old 去头+加尾）
          → 保留已显词，只追加匹配块之后的尾部 → old + tail
        - 重合度过低 → 内容切换（新句子/环境突变）→ 整行替换为 new
        - new 被 old 完全包含（措辞收缩）→ None（已显词不消失，不刷新）
        """
        old = old or ""
        new = (new or "").strip()
        if not new:
            return None
        if not old:
            return new
        if new == old:
            return None  # 完全相同：不刷新
        if new.startswith(old):
            return new
        blocks = [b for b in SequenceMatcher(None, old, new).get_matching_blocks() if b.size > 0]
        if not blocks:
            return new
        matched = sum(b.size for b in blocks)
        if matched / min(len(old), len(new)) < match_ratio:
            return new  # 内容切换：新句子/环境突变
        _, last_j, last_n = blocks[-1]
        tail = new[last_j + last_n:]
        if tail:
            return old + tail
        return None

    def update_partial(self, en: str, zh: str):
        """partial 预览：句子累积打字机——只追加新词，已显词不消失。

        上课字幕只走这条路径（small 短窗，尽量快）。定稿精修不回写字幕。
        与框内解耦：final 写入主窗口积累框；partial 只在
        _accumulate 判定有实质增长时才刷新，措辞抖动/收缩不闪屏。
        """
        en = (en or "").strip()
        new_en = self._accumulate(self._acc_en, en)
        if new_en is None:
            return  # 纯收缩/抖动：保持当前显示
        if new_en == self._acc_en:
            return  # 内容没变
        self._acc_en = new_en
        self._set_en(_tail_clause(new_en, max_chars=56) + " …")
        QTimer.singleShot(0, self._relayout)

    def show_paused(self, paused: bool):
        if paused:
            self._acc_en = ""
            self._set_en("⏸ PAUSED")
        else:
            self._acc_en = ""
            self._set_en("…")
        QTimer.singleShot(0, self._relayout)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, lambda: make_floating(self))


class ControlChip(QWidget):
    """右下角控制条：可交互（非穿透）。点一下获得焦点后可空格/M/Esc。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.on_pause_toggle = None
        self.on_mark = None
        self.on_stop = None
        self.on_toggle = None
        self._paused = False

        self.status = QLabel("● REC")
        self.status.setFont(QFont("PingFang SC", 9))
        self.status.setStyleSheet(
            "color: #7CFC00; background: rgba(0,0,0,150); padding: 2px 6px; border-radius: 6px;")

        self.toggle_btn = QPushButton("字")
        self.toggle_btn.setFixedSize(24, 20)
        self.toggle_btn.setToolTip("显示/隐藏字幕")
        self.toggle_btn.setStyleSheet(_BTN_STYLE)
        self.toggle_btn.clicked.connect(lambda: self.on_toggle and self.on_toggle())

        self.pause_btn = QPushButton("⏸")
        self.pause_btn.setFixedSize(24, 20)
        self.pause_btn.setToolTip("暂停/继续")
        self.pause_btn.setStyleSheet(_BTN_STYLE)
        self.pause_btn.clicked.connect(lambda: self.on_pause_toggle and self.on_pause_toggle())

        self.mark_btn = QPushButton("★")
        self.mark_btn.setFixedSize(24, 20)
        self.mark_btn.setToolTip("打点")
        self.mark_btn.setStyleSheet(_BTN_STYLE)
        self.mark_btn.clicked.connect(lambda: self.on_mark and self.on_mark())

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedSize(24, 20)
        self.stop_btn.setToolTip("结束并保存")
        self.stop_btn.setStyleSheet(_STOP_STYLE)
        self.stop_btn.clicked.connect(self._stop)

        lay = QHBoxLayout(self)
        lay.addWidget(self.status)
        lay.addWidget(self.toggle_btn)
        lay.addWidget(self.pause_btn)
        lay.addWidget(self.mark_btn)
        lay.addWidget(self.stop_btn)
        lay.setContentsMargins(5, 3, 5, 3)
        lay.setSpacing(3)

        self._drag = None
        self._anchor()

    def _anchor(self):
        scr = QGuiApplication.primaryScreen()
        if not scr:
            return
        geo = scr.availableGeometry()
        self.adjustSize()
        self.move(geo.x() + geo.width() - self.width() - 24,
                  geo.y() + geo.height() - self.height() - 48)

    def _toggle_pause(self):
        if self.on_pause_toggle:
            self.on_pause_toggle()

    def _mark(self):
        if self.on_mark:
            self.on_mark()
            self.mark_btn.setText("✓")
            QTimer.singleShot(500, lambda: self.mark_btn.setText("★"))

    def _stop(self):
        # 只转发：确认逻辑统一在主窗口 on_stop，避免控制条与主窗口双重确认
        if self.on_stop:
            self.on_stop()

    def set_paused(self, paused: bool):
        self._paused = paused
        if paused:
            self.status.setText("⏸ PAUSE")
            self.status.setStyleSheet(
                "color: #FFD166; background: rgba(0,0,0,170); padding: 4px 8px; border-radius: 8px;")
            self.pause_btn.setText("▶")
        else:
            self.status.setText("● REC")
            self.status.setStyleSheet(
                "color: #7CFC00; background: rgba(0,0,0,150); padding: 4px 8px; border-radius: 8px;")
            self.pause_btn.setText("⏸")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, lambda: make_floating(self))
