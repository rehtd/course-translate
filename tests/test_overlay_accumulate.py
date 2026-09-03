"""句子累积打字机核心逻辑测试（不依赖 Qt 窗口）。

运行: <venv>/bin/python -m pytest tests/test_overlay_accumulate.py -q
或:   <venv>/bin/python tests/test_overlay_accumulate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.overlay import SubtitleBar

acc = SubtitleBar._accumulate


def test_empty_old():
    assert acc("", "hello world") == "hello world"


def test_empty_new():
    assert acc("hello world", "") is None
    assert acc("hello world", "   ") is None


def test_typing_growth_prefix():
    """打字机正常增长：new 以 old 开头 → 直接返回 new。"""
    assert acc("Today we discuss", "Today we discuss quant") == "Today we discuss quant"


def test_window_slide_head_cut():
    """5s 窗口滑头：old 开头被切，new = old 去头 + 追加尾部 → 保留已显，追加尾部。"""
    old = "Today we discuss quant"
    new = "we discuss quant investment strategies"
    assert acc(old, new) == "Today we discuss quant investment strategies"


def test_content_switch_low_overlap():
    """内容切换（低重合）→ 整行替换。"""
    old = "And then we move on"
    new = "Now regression is the key topic"
    assert acc(old, new) == new


def test_shrink_no_refresh():
    """措辞收缩（new 被 old 包含）→ None，已显词不消失。"""
    old = "Today we discuss quant investment"
    new = "Today we discuss quant"
    assert acc(old, new) is None


def test_identical_no_refresh():
    assert acc("same text", "same text") is None


def test_zh_typing_growth():
    assert acc("今天我们来讨论", "今天我们来讨论量化策略") == "今天我们来讨论量化策略"


def test_zh_window_slide():
    old = "今天我们来讨论量化投资"
    new = "我们来讨论量化投资的应用场景"
    assert acc(old, new) == "今天我们来讨论量化投资的应用场景"


def test_zh_content_switch():
    old = "我们先看这个例子"
    new = "接下来讲回归分析"
    assert acc(old, new) == new


def test_single_word_drift():
    """措辞微调但整体同一句 → 不应整行替换；无尾部新增时返回 None（final 再替换）。"""
    old = "we discuss quant investment strategies"
    new = "we discuss the quant investment strategies"  # 插了个 the
    r = acc(old, new)
    # 允许 None（中间插入，无尾部新增）；或合法增长；但绝不允许 = new 整行替换
    assert r is None or r.startswith(old)


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
