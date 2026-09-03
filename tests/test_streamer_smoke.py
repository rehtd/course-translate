"""v3.5 流畅度优化单元测试（offscreen，无显示）：
1. StreamingEngine 短窗双轨：partial 用 partial_asr_win(3s)、final 用 asr_win(5s)
2. partial_win=1.2s 触发频率
3. _same_sentence 新判据（时间窗重叠 + 长度 + 文本覆盖）：
   - 同句重发 → 判同（跳过）
   - 短窗尾部片段重发 → 判同（防重复定稿，Agent B 场景 D1）
   - 残句补全（长度增长）→ 放行
   - 窗口不重叠 → 放行
   - 快速连续不同句 + 重叠窗口 → 放行

运行: QT_QPA_PLATFORM=offscreen <venv>/bin/python tests/test_streamer_smoke.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.streamer import StreamingEngine  # noqa: E402
from app.recorder import _same_sentence  # noqa: E402


def test_partial_short_win_final_long_win():
    """短窗双轨：partial 喂 3s 窗、final 喂 5s 窗。"""
    sr = 16000
    got = {"partial": [], "final": []}

    def on_partial(audio, t0, t1):
        got["partial"].append((len(audio), t0, t1))

    def on_final(audio, t0, t1):
        got["final"].append((len(audio), t0, t1))

    eng = StreamingEngine(sr=sr, partial_win=1.2, asr_win=5.0,
                          partial_asr_win=3.0, ring_sec=9.0,
                          on_partial=on_partial, on_final=on_final)
    # 喂 8s 静音（0.1s 块）
    block = np.zeros(int(sr * 0.1), dtype=np.float32)
    for i in range(80):
        eng.feed(block, (i + 1) * 0.1)
    # partial：每 1.2s 触发一次 → 8/1.2 ≈ 6 次；窗口 = min(partial_asr_win, ring 已攒时长)
    assert len(got["partial"]) >= 5, f"partial 触发次数: {len(got['partial'])}"
    # ring 攒满 3s 后（启动后 ~3s），窗口应恒为 3s
    for n, t0, t1 in got["partial"]:
        assert n <= int(3.0 * sr), f"partial 窗不应超过 3s: {n}"
    assert got["partial"][-1][0] == int(3.0 * sr), "ring 满后 partial 窗应恒为 3s"
    assert max(n for n, _, _ in got["partial"]) == int(3.0 * sr), "应出现过 3s 全窗"
    # final：5s 窗
    eng.finalize(8.0)
    assert got["final"] and got["final"][0][0] == int(5.0 * sr), "final 窗应 5s"
    # 触发间隔：相邻 partial 至少 1.2s
    ts = [t1 for _, _, t1 in got["partial"]]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    assert all(g >= 1.19 for g in gaps), f"partial 间隔应 ≥1.2s: {gaps}"
    print("[OK] 短窗双轨：partial=3s / final=5s，触发间隔 1.2s")


def test_finalize_span_from_last():
    """框内定稿：from_t 切 [上一句切点, 现在] 整段，而不是固定尾 5s。"""
    sr = 16000
    got = []

    def on_final(audio, t0, t1):
        got.append((len(audio) / sr, t0, t1))

    eng = StreamingEngine(sr=sr, partial_win=1.2, asr_win=5.0,
                          partial_asr_win=3.0, ring_sec=12.0,
                          on_final=on_final)
    block = np.zeros(int(sr * 0.1), dtype=np.float32)
    for i in range(80):  # 8s
        eng.feed(block, (i + 1) * 0.1)
    eng.finalize(8.0, from_t=0.0)
    assert got, "应产出一次定稿"
    dur, t0, t1 = got[0]
    assert abs(dur - 8.0) < 0.05, f"应送满 8s 而非尾 5s: {dur:.2f}s"
    assert abs(t0 - 0.0) < 0.05 and abs(t1 - 8.0) < 0.05
    # 未传 from_t 时回退固定尾窗
    got.clear()
    eng.finalize(8.0)
    assert abs(got[0][0] - 5.0) < 0.05, f"默认仍应 5s 尾窗: {got[0][0]:.2f}s"
    print("[OK] 定稿可变窗：from_t=0 送 8s；默认仍 5s 尾窗")


def test_same_sentence_same_text():
    """同句重发（相同文本 + 高度重叠窗口）→ 判同。"""
    assert _same_sentence("the gradient descent is stable.",
                          "the gradient descent is stable.",
                          win_overlap=0.95) is True
    print("[OK] 同句重发判同")


def test_same_sentence_tail_fragment():
    """短窗尾部片段重发（Agent B D1 场景）：文本前缀断裂但同音频 → 判同防重复。"""
    a = "times the gradient."
    b = "the loss times the gradient is large."
    assert _same_sentence(a, b, win_overlap=0.9) is True, "短窗尾部片段应判同（防重复定稿）"
    print("[OK] 短窗尾部片段判同（防重复定稿）")


def test_same_sentence_completion_release():
    """残句补全：长度明显增长 → 放行（不能丢内容）。"""
    a = "the loss gradient descent is stable."
    b = "the loss gradient descent"
    assert _same_sentence(a, b, win_overlap=0.9) is False, "残句补全必须放行"
    print("[OK] 残句补全放行")


def test_same_sentence_win_no_overlap():
    """时间窗不重叠 → 放行（新句子）。"""
    assert _same_sentence("the gradient descent is stable.",
                          "the gradient descent is stable.",
                          win_overlap=0.3) is False, "窗口不重叠应放行"
    print("[OK] 窗口不重叠放行")


def test_same_sentence_different_sentences():
    """快速连续不同句 + 重叠窗口 + 文本不同 → 放行。"""
    a = "next we look at the results"
    b = "the gradient descent is stable"
    assert _same_sentence(a, b, win_overlap=0.8) is False, "不同句子应放行"
    print("[OK] 不同句子放行")


def test_partial_win_default_fallback():
    """partial_asr_win 未指定时回退 asr_win（兼容旧行为，main.py 等）。"""
    eng = StreamingEngine(sr=16000, partial_win=1.5, asr_win=5.0)
    assert eng.partial_asr_win == 5.0
    print("[OK] partial_asr_win 默认回退 asr_win")


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
