"""术语表解析、翻译重试、失败句重补。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.storage import Store  # noqa: E402
from app.translate import (  # noqa: E402
    DeepSeekTranslator, asr_initial_prompt, build_context_user,
    en_truncated, format_glossary_text, glossary_prompt, is_retryable,
    join_en, looks_cut, parse_glossary_text, pending_truncated, should_stitch,
    translate_with_retry,
)


def test_parse_glossary_text():
    terms = parse_glossary_text(
        "# skip\nJohns Hopkins = 约翰·霍普金斯\n"
        "data visualization：数据可视化\n"
        "Johns Hopkins = 重复应忽略\n"
        "badline\n = empty\n")
    assert terms == [
        ("Johns Hopkins", "约翰·霍普金斯"),
        ("data visualization", "数据可视化"),
    ]
    assert "约翰·霍普金斯" in glossary_prompt(terms)
    assert format_glossary_text(terms).startswith("Johns Hopkins =")
    assert "Johns Hopkins" in asr_initial_prompt(terms)
    print("PASS parse_glossary_text")


def test_glossary_in_system_prompt():
    t = DeepSeekTranslator(api_key="x")
    t.set_glossary([("gradient descent", "梯度下降")])
    sys_p = t._system("BASE")
    assert "BASE" in sys_p
    assert "gradient descent = 梯度下降" in sys_p
    print("PASS glossary_in_system_prompt")


def test_retry_then_success():
    class Flaky:
        def __init__(self):
            self.n = 0

        def translate(self, text, context=None):
            self.n += 1
            if self.n < 2:
                raise TimeoutError("timed out")
            return "梯度下降"

    t = Flaky()
    sleeps = []
    zh = translate_with_retry(t, "gradient descent", attempts=3,
                               sleep=lambda s: sleeps.append(s))
    assert zh == "梯度下降"
    assert t.n == 2
    assert sleeps
    print("PASS retry_then_success")


def test_en_truncated_and_stitch():
    assert looks_cut("when we look at the") is True
    assert looks_cut("This is important") is False
    assert looks_cut("This is done.") is False
    assert should_stitch("when we look at the", "gradient descent method.") is True
    assert should_stitch("when we look at the", "gradient descent") is True
    assert should_stitch("This is the end of the story", "Next we discuss risk.") is False
    assert should_stitch("OK.", "Let's continue.") is False
    chain = pending_truncated([
        (1, "hello there.", "你好。"),
        (2, "when we look at the", ""),
    ])
    assert chain == [(2, "when we look at the")]
    assert join_en("when we look at the", "gradient descent.") == (
        "when we look at the gradient descent.")
    user = build_context_user("gradient descent.", [("when we look at the", "")])
    assert "后半段" in user
    user2 = build_context_user("when we look at the", None)
    assert "截断" in user2
    print("PASS en_truncated_and_stitch")


def test_translate_final_defers_then_stitches():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.recorder import Recorder

    class Tsl:
        def __init__(self):
            self.calls = []

        def translate(self, text, context=None):
            self.calls.append(text)
            return f"ZH:{text}"

    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td) / "t.db")
        sid = store.create_session("t")
        tsl = Tsl()
        rec = Recorder(store, None, tsl)
        rec.session_id = sid
        rec._stop_ev.clear()
        rec.paused_ev.clear()
        zh1 = rec._translate_final(store, tsl, sid, 1, "when we look at the")
        assert zh1 == ""
        assert tsl.calls == []
        store.add_segment(sid, 1, 0, 1, "when we look at the", zh1)
        zh2 = rec._translate_final(store, tsl, sid, 2, "gradient descent method.")
        assert zh2 == "ZH:when we look at the gradient descent method."
        assert tsl.calls == ["when we look at the gradient descent method."]
        row = store.conn.execute(
            "SELECT translated_text FROM segments WHERE session_id=? AND seq=1",
            (sid,)).fetchone()
        assert row[0] == zh2
    print("PASS translate_final_defers_then_stitches")


def test_auth_error_no_retry():
    class Boom:
        def translate(self, text, context=None):
            raise RuntimeError("401 invalid api key")

    assert not is_retryable("401 invalid api key")
    zh = translate_with_retry(Boom(), "hi", attempts=5, sleep=lambda s: None)
    assert zh.startswith("[翻译失败]")
    print("PASS auth_error_no_retry")


def test_glossary_and_failed_segments_store():
    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td) / "t.db")
        cid = store.add_course("IS6335", "Data Visualization")
        store.replace_glossary(cid, [("Johns Hopkins", "约翰·霍普金斯")])
        assert store.list_glossary(cid) == [("Johns Hopkins", "约翰·霍普金斯")]
        sid = store.create_session("第 1 节", course_id=cid)
        store.add_segment(sid, 1, 1, 2, "hello", "你好")
        store.add_segment(sid, 2, 3, 4, "oops", "[翻译失败] timeout")
        failed = store.list_failed_segments(sid)
        assert len(failed) == 1 and failed[0][0] == 2
        store.update_segment_zh(sid, 2, "修好了")
        assert store.list_failed_segments(sid) == []
        store.delete_course(cid)
        assert store.list_glossary(cid) == []
        print("PASS glossary_and_failed_segments_store")


def test_upsert_glossary_keeps_other_terms():
    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td) / "t.db")
        cid = store.add_course("IS6335", "DV")
        store.replace_glossary(cid, [("A", "甲"), ("B", "乙")])
        store.upsert_glossary_terms(cid, [("C", "丙"), ("A", "甲二")])
        got = dict(store.list_glossary(cid))
        assert got["A"] == "甲二"
        assert got["B"] == "乙"
        assert got["C"] == "丙"
        print("PASS upsert_glossary_keeps_other_terms")


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
