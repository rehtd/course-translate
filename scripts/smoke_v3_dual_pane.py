"""双区架构无头冒烟：布局、英中双框、字幕只显英文。
1. MainWindow 四栏 split（课程/课节/回看列表/录制双框，按 workspace 显隐）
2. _append_zh / _append_en 累积 + 自动滚底
3. _upsert_partial 只上屏英文（卡片 zh 隐藏）
4. _SegmentCard / _FullRow 空 zh 隐藏
5. overlay 只显英文、固定单行高度 66、短句化保留末尾
5c. 录制双框累积、切会话清空
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DEEPSEEK_API_KEY"] = "sk-test-dummy"  # 避免导入时报错

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication, QSplitter
from PySide6.QtCore import QTimer

app = QApplication([])

# ---- 1/2: MainWindow 布局 ----
from app.storage import Store
from app.ui.main_window import MainWindow

from pathlib import Path
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_smoke_v3.db")
if os.path.exists(db_path):
    os.remove(db_path)
store = Store(Path(db_path))
win = MainWindow(store)

splitters = win.findChildren(QSplitter)
assert splitters, "找不到 splitter"
sp = win._split
n = sp.count()
print(f"[OK] split 栏数 = {n}")
assert n == 4, f"期望 4 栏（课程序/课节/转写/右侧双框），实际 {n}"
assert hasattr(win, "zh_box") and hasattr(win, "en_box"), "缺少右侧双积累框"
print(f"[OK] zh_box 只读 = {win.zh_box.isReadOnly()}，en_box 只读 = {win.en_box.isReadOnly()}")
assert win._workspace == "review"
assert win.right_split.isHidden() and not win.transcript.isHidden()
win._apply_workspace("record")
assert win.transcript.isHidden() and not win.right_split.isHidden()
win._apply_workspace("review")
print("[OK] workspace review/record 显隐切换")

# 模拟定稿句累积
win._append_zh("这是第一句译文。")
win._append_zh("这是第二句译文，长一点，验证换行。")
txt = win.zh_box.toPlainText()
assert "这是第一句译文。" in txt and "这是第二句译文" in txt, f"累积内容不对: {txt!r}"
sb = win.zh_box.verticalScrollBar()
assert sb.value() == sb.maximum(), "未自动滚底"
print(f"[OK] zh_box 累积 {len(txt)} 字符，已滚底")

win.zh_box.setFixedHeight(140)
for i in range(30):
    win._append_zh(f"用来撑出滚动条的第 {i} 句译文。")
app.processEvents()
sb = win.zh_box.verticalScrollBar()
assert sb.maximum() > 0, "应出现滚动条"
sb.setValue(0)
app.processEvents()
assert win._zh_sticky is False, "滚到顶部后不应再跟随"
held = sb.value()
win._append_zh("新来的一句不应该把我拉走")
app.processEvents()
assert sb.value() <= held + 8, f"看历史时被拉走: {held} -> {sb.value()}"
print("[OK] zh_box 往上翻看时新句不拉回底部")
win.zh_box.setFixedHeight(16777215)  # 取消测试用固定高度

# ---- 3: partial 英文-only ----
win._upsert_partial("the professor is explaining", "")
assert win._partial_card is not None, "partial 卡未创建"
card = win._partial_card
assert card.zh_text == "", "partial zh_text 应为空"
assert card.zh.isHidden(), "partial 中文行应显式隐藏"
assert not card.en.isHidden(), "partial 英文行不应隐藏"
print(f"[OK] partial 卡英文-only：en='{card.en.text()[:30]}…' zh 隐藏")

# ---- 4: _FullRow 空 zh 隐藏 ----
from app.ui.main_window import _FullRow
fr_partial = _FullRow("00:00:05", "some partial english", "", "partial")
assert fr_partial._has_zh is False and fr_partial.zh_lbl.isHidden(), "FullRow partial 空 zh 应隐藏"
fr_dual = _FullRow("00:01:00", "hello", "你好", "final")
assert fr_dual._has_zh is True and not fr_dual.zh_lbl.isHidden(), "FullRow final 有 zh 应显示"
fr_dual.set_lang("en")
assert fr_dual.zh_lbl.isHidden(), "set_lang('en') 后 zh 应隐藏"
fr_dual.set_lang("zh")
assert not fr_dual.zh_lbl.isHidden(), "set_lang('zh') 后 zh 应显示"
print("[OK] _FullRow 空 zh 隐藏 + set_lang 联动正常")

# ---- 5: overlay 只显英文 + 固定单行高度 ----
# 注意：offscreen 平台不支持悬浮窗 raise()，不 show，直接调方法断言（isHidden 不依赖显示）
from app.overlay import SubtitleBar
bar = SubtitleBar()
bar.setFixedWidth(1200)
bar.en.setFixedWidth(1152)
bar.update_text("the professor is explaining the concept", "教授正在讲解这个概念")
app.processEvents()
assert bar.height() == 66, f"只显英文单行固定高度应 66，实际 {bar.height()}"
assert bar.en.text() == "the professor is explaining the concept", f"英文应整句显示: {bar.en.text()!r}"
bar.update_partial("the professor is explaining the concept of", "")
app.processEvents()
assert "…" in bar.en.text(), "英文应带省略号"
assert bar.height() == 66, f"partial 后高度仍应 66: {bar.height()}"
print(f"[OK] overlay 只显英文：en='{bar.en.text()}' 高度固定 66")

# ---- 5b: 短句化 + 固定高度 ----
bar.update_text("This is the first sentence. This is the second sentence.", "这是第一句。这是第二句。")
app.processEvents()
assert bar.en.text() == "This is the second sentence.", f"final 应显示尾句: {bar.en.text()!r}"
print(f"[OK] final 短句化：en='{bar.en.text()}'")

long_talk = ("the professor is explaining a very very long concept "
             "that keeps growing and growing and growing and growing")
bar.update_partial(long_talk, "")
app.processEvents()
assert "…" in bar.en.text(), "长句 partial 应带省略号"
assert len(bar.en.text()) < len(long_talk) + 2, f"长句应短句化: {bar.en.text()!r}"
assert "growing" in bar.en.text(), "短句化应保留末尾内容"
assert bar.height() == 66, f"长句不改变窗口高度: {bar.height()}"
print(f"[OK] partial 长句短句化：len={len(bar.en.text())} en='{bar.en.text()}'")

# 空英文 → 状态占位显示在主行（启动「等待老师讲课…」）
bar.update_text("", "等待老师讲课…")
app.processEvents()
assert "等待老师讲课" in bar.en.text(), "空英文时应保留中文占位"
print("[OK] 空英文保留中文状态占位")

# 暂停/恢复
bar.show_paused(True)
app.processEvents()
assert "PAUSED" in bar.en.text(), "暂停时主行应显示 PAUSED"
bar.show_paused(False)
app.processEvents()
print("[OK] overlay 暂停/恢复 en 正常")

# ---- 5d: 定稿写入框内，不回写悬浮字幕 ----
win.bar = bar
bar.update_partial("live subtitle about the next topic", "")
app.processEvents()
live = bar.en.text()
win._on_seg(1, 1.0, 2.0, "previous sentence finalized accurately", "上一句精修译文")
app.processEvents()
assert bar.en.text() == live, f"定稿不应改写字幕: {bar.en.text()!r} vs {live!r}"
assert "previous sentence finalized accurately" in win.en_box.toPlainText()
assert "上一句精修译文" in win.zh_box.toPlainText()
print("[OK] 定稿进框内、字幕仍跟 live partial")

# ---- 5c: 右侧双积累框（英文原文 + 中文译文）----
win._append_en("First sentence in English.")
win._append_en("Second sentence, longer.")
en_txt = win.en_box.toPlainText()
assert "First sentence in English." in en_txt and "Second sentence" in en_txt, f"英文积累不对: {en_txt!r}"
assert win.en_box.verticalScrollBar().value() == win.en_box.verticalScrollBar().maximum(), "en_box 未自动滚底"
assert win.zh_box.toPlainText() != "", "zh_box 仍应保留中文译文"
print("[OK] 右侧双框：en_box 累积英文 + 滚底，zh_box 中文保留")

# 切会话清空两个框
win._clear_transcript()
assert win.en_box.toPlainText() == "" and win.zh_box.toPlainText() == "", "切会话应清空双框"
print("[OK] 切会话清空英文/中文双框")

win.close()
bar.close()
store.close() if hasattr(store, "close") else None
os.remove(db_path)
print("\n=== 冒烟测试全部通过 ===")
QTimer.singleShot(0, app.quit)
app.processEvents()
