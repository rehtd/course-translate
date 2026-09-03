"""课后术语提取：切块、规范化、与已有表分类（无网络）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.glossary_extract import (  # noqa: E402
    chunk_pairs, classify_candidates, normalize_candidates, pairs_from_segments,
)
from app.note_agent import extract_json  # noqa: E402


def test_pairs_skip_failures():
    rows = [
        (1, 0, 1, "hello Hopkins", "你好霍普金斯"),
        (2, 0, 1, "[ASR错误] x", "（未识别到清晰语音）"),
        (3, 0, 1, "ok", "[翻译失败] timeout"),
        (4, 0, 1, "", "空"),
    ]
    assert pairs_from_segments(rows) == [("hello Hopkins", "你好霍普金斯")]
    print("PASS pairs_skip_failures")


def test_chunk_pairs():
    pairs = [(f"en{i}", f"zh{i}") for i in range(20)]
    chunks = chunk_pairs(pairs, max_chars=40)
    assert len(chunks) >= 2
    flat = [p for c in chunks for p in c]
    assert len(flat) == 20
    print("PASS chunk_pairs")


def test_normalize_and_classify():
    raw = extract_json(
        '{"terms": [{"en": "Johns Hopkins", "zh": "约翰·霍普金斯", "reason": "学校"},'
        ' {"en": "chart", "zh": "图表"}]}')
    cand = normalize_candidates(raw)
    assert cand[0]["en"] == "Johns Hopkins"
    rows = classify_candidates(cand, [("Johns Hopkins", "约翰霍普金斯"), ("foo", "条")])
    by = {r["en"]: r for r in rows}
    assert by["Johns Hopkins"]["action"] == "改译"
    assert by["chart"]["action"] == "新建"
    same = classify_candidates(
        [{"en": "foo", "zh": "条", "reason": ""}], [("foo", "条")])
    assert same[0]["action"] == "已有"
    print("PASS normalize_and_classify")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
        except Exception:
            fails += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
