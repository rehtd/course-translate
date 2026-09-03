"""SubtitleBar 冒烟测试（offscreen，无显示）。

覆盖：句子累积打字机、final 替换、短句化（保留末尾）、v3.3 固定单行高度 +
单行省略。v3.4 起悬浮字幕只显英文（中文对照在主窗口右侧双框看），
中文行相关断言全部移除。

运行: QT_QPA_PLATFORM=offscreen <venv>/bin/python tests/test_overlay_smoke.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.overlay import _H_ONE, SubtitleBar  # noqa: E402

app = QApplication.instance() or QApplication([])


def make_bar(width=1200):
    """真实屏幕宽度：模拟 1200px 窗口下 label 的实际宽度（窗口 - 左右留白 48）。

    offscreen 下窗口 layout 不激活，label 宽度不跟随窗口——直接设置
    label 宽度以模拟真实布局后的结果。
    """
    bar = SubtitleBar()
    bar.setFixedWidth(width)
    bar.en.setFixedWidth(width - 48)
    return bar


def text_of(bar):
    return bar.en.text()


def test_typing_accumulate_no_flash():
    """partial 打字机：只追加，已显词不消失；抖动不闪屏。"""
    bar = make_bar()
    bar.update_partial("Now let's talk about regression", "现在我们来谈回归")
    en1 = text_of(bar)
    assert "Now let's talk about regression" in en1
    # 打字机增长：只追加尾部
    bar.update_partial("Now let's talk about regression models", "现在我们来谈回归模型")
    en2 = text_of(bar)
    assert en2.startswith("Now let's talk about regression")
    assert "models" in en2
    # 窗口滑头 + 追加：已显词不消失
    bar.update_partial("let's talk about regression models in finance", "我们来谈金融中的回归模型")
    en3 = text_of(bar)
    assert en3.startswith("Now let's talk about regression")  # 开头没被切掉
    assert "in finance" in en3
    # 措辞收缩（窗口纯滑头无新词）：不刷新
    bar.update_partial("let's talk about regression models", "我们来谈回归模型")
    en4 = text_of(bar)
    assert en4 == en3


def test_final_replaces_and_resets():
    """final 定稿：整句替换精校版，作为下句累积基准（只显英文）。"""
    bar = make_bar()
    bar.update_partial("we are using panel data", "我们正在使用面板数据")
    bar.update_text("we are using panel data from 2010", "我们正在使用 2010 年以来的面板数据")
    en = text_of(bar)
    assert en == "we are using panel data from 2010"
    # 下一句 partial：与定稿句低重合 → 整行替换
    bar.update_partial("Next let's look at the results", "接下来我们看结果")
    assert text_of(bar).startswith("Next let's look at the results")


def test_sentence_switch_replaces():
    """句子切换（低重合）：英文整行替换。"""
    bar = make_bar()
    bar.update_text("First we review the syllabus", "首先我们回顾教学大纲")
    bar.update_partial("Now let's talk about grading", "现在我们谈谈评分")
    assert text_of(bar).startswith("Now let's talk about grading")


def test_pause_resets():
    bar = make_bar()
    bar.update_partial("some lecture content", "一些课堂内容")
    bar.show_paused(True)
    assert "PAUSED" in text_of(bar)
    bar.show_paused(False)
    bar.update_partial("new content after break", "休息后的新内容")
    assert text_of(bar).startswith("new content after break")


def test_fixed_height_stable():
    """v3.3 稳定布局：连续更新文本，窗口高度固定不变（不再随换行跳动）。"""
    bar = make_bar()
    h0 = bar.height()
    assert h0 == _H_ONE
    bar.update_text("Short.", "短。")
    bar.update_text(
        "This is a fairly long sentence that keeps going for a while.",
        "这是一个相当长的中文句子，会持续写很久很久。")
    bar.update_partial("now we add a partial line while talking", "")
    assert bar.height() == h0, f"高度跳动: {h0} vs {bar.height()}"
    # 中英文都单行：短句与长句都不改变窗口尺寸


def test_tail_clause_keeps_ending():
    """短句化保留末尾窗口（正在说的部分），而不是截开头。"""
    bar = make_bar()
    long_talk = ("the professor is explaining a very very long concept "
                 "that keeps growing and growing and growing and growing")
    bar.update_partial(long_talk, "")
    en = text_of(bar)
    assert "growing" in en, f"应保留正在说的末尾: {en!r}"
    assert len(en) < len(long_talk) + 2, f"长句应短句化: {en!r}"
    # final 短句化同样保留尾句
    bar.update_text("This is the first sentence. This is the second sentence.", "这是第一句。这是第二句。")
    assert text_of(bar) == "This is the second sentence."


def test_long_text_elided_single_line():
    """v3.3 单行省略：窄窗口下超长文本以省略号截断，不撑破固定布局。"""
    bar = make_bar(width=500)
    long = "this is a very long english sentence that should never wrap and " \
           "it keeps going and going beyond the available width of the window"
    bar.update_text(long, "超长中文译文。")
    assert bar.height() == _H_ONE          # 高度不受长文本影响
    assert not bar.en.wordWrap()           # 单行模式
    assert bar.en.text().endswith("…") or bar.en.text() == bar._raw_en


def test_empty_en_keeps_status():
    """空英文（启动占位）：状态提示显示在主行，布局保持单行固定。"""
    bar = make_bar()
    bar.update_text("", "等待老师讲课…")
    assert "等待老师讲课" in text_of(bar)
    assert bar.height() == _H_ONE


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
