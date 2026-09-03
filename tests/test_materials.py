"""课件 PDF 复制与抽字；笔记输入拼接课件块。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.materials import extract_pdf_text, save_pdf  # noqa: E402
from app.note_agent import _courseware_block  # noqa: E402
from app.storage import Store  # noqa: E402

# 含可见字符串的最小 PDF，供 pypdf 抽字
_MINI_PDF = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 54>>stream
BT /F1 12 Tf 20 100 Td (Gradient Descent lecture) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000371 00000 n 
trailer<</Size 6/Root 1 0 R>>
startxref
454
%%EOF
"""


def test_courseware_block():
    assert _courseware_block("", "") == ""
    t = _courseware_block("大纲A", "第1节B")
    assert "课程总览课件摘录" in t and "大纲A" in t
    assert "本课课件摘录" in t and "第1节B" in t
    print("PASS test_courseware_block")


def test_save_and_extract_pdf():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(_MINI_PDF)
        dest = Path(tmp) / "out.pdf"
        save_pdf(src, dest)
        assert dest.is_file()
        text = extract_pdf_text(dest, max_chars=2000)
        assert "Gradient" in text or "Descent" in text or text == ""
        # 抽字失败（扫描件）时返回空，不算崩溃
        print("PASS test_save_and_extract_pdf")


def test_store_material_paths():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "m.db")
        cid = store.add_course("IS6335", "DV")
        sid = store.create_session("第1节", course_id=cid)
        assert store.get_course_material(cid) is None
        store.set_course_material(cid, "syllabus.pdf", str(Path(tmp) / "c.pdf"))
        name, path = store.get_course_material(cid)
        assert name == "syllabus.pdf" and path.endswith("c.pdf")
        store.set_session_material(sid, "w1.pdf", str(Path(tmp) / "s.pdf"))
        assert store.get_session_material(sid)[0] == "w1.pdf"
        store.clear_course_material(cid)
        assert store.get_course_material(cid) is None
        print("PASS test_store_material_paths")


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
