"""v3.6 周期定稿防腰斩单元测试：_sentence_incomplete 判定（offscreen，无显示）。

覆盖：
- 句子未完（无终止标点）+ 正在说话（高能量/近 talk）→ 跳过定稿（True）
- 句子带终止标点 → 正常定稿（False）
- 说完停顿（无标点 + 低能量 + talk 远）→ 正常定稿（False）
- 未超上限 vs 超上限（_PENDING_MAX 兜底强制定稿）

运行: <venv>/bin/python tests/test_finalize_policy.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.recorder import _sentence_incomplete  # noqa: E402


def test_mid_sentence_loud():
    """句中说一半 + 能量高 → 跳过（防腰斩丢尾词）。"""
    assert _sentence_incomplete("today you will meet", rms=0.05, talk_gap=0.5, since=5.0) is True
    print("PASS mid_sentence_loud")


def test_mid_sentence_quiet_but_talking():
    """句中说一半 + 低音量（外放/远场）但最近有说话 → 跳过。"""
    assert _sentence_incomplete("email me before you", rms=0.005, talk_gap=0.8, since=5.0) is True
    print("PASS mid_sentence_quiet_but_talking")


def test_sentence_finished_punct():
    """带终止标点（句子说完）→ 正常定稿。"""
    assert _sentence_incomplete("meet at 2 p.m.", rms=0.05, talk_gap=0.5, since=5.0) is False
    assert _sentence_incomplete("finish it!", rms=0.05, talk_gap=0.5, since=5.0) is False
    print("PASS sentence_finished_punct")


def test_finished_pause_no_punct():
    """说完停顿（无标点但静音、talk 已远）→ 正常定稿。"""
    assert _sentence_incomplete("today you will meet", rms=0.002, talk_gap=4.0, since=5.0) is False
    print("PASS finished_pause_no_punct")


def test_over_pending_max():
    """等待超过上限 → 强制定稿兜底（防长句无限跳过）。"""
    assert _sentence_incomplete("still talking no stop", rms=0.05, talk_gap=0.3, since=11.0) is False
    print("PASS over_pending_max")


def test_empty_text():
    """无文本（静音段）→ 不跳过。"""
    assert _sentence_incomplete("", rms=0.001, talk_gap=0.1, since=5.0) is False
    print("PASS empty_text")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            fails += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
