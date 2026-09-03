"""笔记 Agent：JSON 契约 / 相对时间戳 / 长课切块（无网络）。"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.note_agent import (  # noqa: E402
    empty_draft, extract_json, normalize_draft, rel_timestamp,
    split_transcript, NoteAgent,
)
from app.storage import Store  # noqa: E402


def test_extract_json_fence():
    raw = extract_json('```json\n{"short_title": "梯度下降", "concepts": []}\n```')
    assert raw["short_title"] == "梯度下降"
    print("PASS extract_json_fence")


def test_normalize_fills_index_from_concepts():
    d = normalize_draft({
        "short_title": "GD",
        "one_liner": "沿梯度下山",
        "concepts": [{"name": "梯度下降", "en": "Gradient Descent",
                      "one_liner": "沿梯度反方向更新", "points": ["学习率"]}],
    })
    assert d["knowledge_index"][0]["name"] == "梯度下降"
    assert d["concepts"][0]["en"] == "Gradient Descent"
    print("PASS normalize_fills_index")


def test_normalize_string_index():
    d = normalize_draft({"knowledge_index": ["学习率"], "concepts": []})
    assert d["knowledge_index"][0]["name"] == "学习率"
    assert any(c["name"] == "学习率" for c in d["concepts"])
    print("PASS normalize_string_index")


def test_rel_timestamp():
    origin = 1_000_000.0
    assert rel_timestamp(origin + 65, origin) == "01:05"
    assert rel_timestamp(origin + 3700, origin) == "1:01:40"
    assert rel_timestamp(origin - 10, origin) == "00:00"
    print("PASS rel_timestamp")


def test_split_transcript():
    text = "a\n" * 100
    parts = split_transcript(text, max_chars=50)
    assert len(parts) >= 2
    assert "".join(p + "\n" for p in parts).replace("\n\n", "\n").count("a") >= 90
    print("PASS split_transcript")


def test_empty_draft():
    d = empty_draft("第1节")
    assert d["knowledge_index"] == []
    assert "没有可整理" in d["one_liner"]
    print("PASS empty_draft")


def test_build_input_skips_noise_and_pause():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "n.db")
        t0 = datetime.now().replace(microsecond=0)
        sid = store.create_session(title="t")
        # 把 started_at 钉在已知时间：直接 update
        store.conn.execute(
            "UPDATE sessions SET started_at=? WHERE id=?",
            (t0.isoformat(timespec="seconds"), sid))
        store.conn.commit()
        origin = t0.timestamp()
        store.add_segment(sid, 1, origin + 5, origin + 6, "hello gradient", "你好")
        store.add_segment(sid, 2, origin + 10, origin + 11, "[ASR错误] boom", "")
        store.add_marker(sid, origin + 8, "pause", "⏸ 暂停")
        store.add_marker(sid, origin + 12, "user", "作业")
        agent = NoteAgent(store)
        text = agent.build_input(sid)
        assert "hello gradient" in text
        assert "你好" in text
        assert "[ASR错误]" not in text
        assert "暂停" not in text
        assert "作业" in text
        assert "[00:05]" in text
        print("PASS build_input_skips_noise")


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
