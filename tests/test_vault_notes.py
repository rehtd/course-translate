"""课节页渲染、概念卡 upsert、概览追加。"""
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.vault_notes import (  # noqa: E402
    VaultMeta, course_folder_name, lecture_stem, render_lecture,
    write_vault, inspect_concepts, find_concept_path,
)


def _meta(root: Path) -> VaultMeta:
    return VaultMeta(
        vault=root,
        notes_subdir="01-章节笔记",
        concepts_subdir="02-概念卡片",
        course_code="IS5113",
        course_name="IS5113",
        session_id=42,
        lecture_n=3,
        created="2026-09-02",
    )


def _draft():
    return {
        "short_title": "梯度下降",
        "one_liner": "沿梯度反方向更新参数。",
        "knowledge_index": [
            {"name": "梯度下降", "note": "这节讲了更新公式"},
            {"name": "学习率", "note": ""},
        ],
        "sections": [{"title": "更新公式", "markdown": "参数减去学习率乘梯度。"}],
        "homework": ["周五交作业"],
        "questions": [],
        "anchors": [{"t": "12:04", "quote": "过大则震荡"}],
        "concepts": [
            {
                "name": "梯度下降",
                "en": "Gradient Descent",
                "one_liner": "沿梯度反方向走。",
                "detail": "最常见的一阶优化。",
                "points": ["更新：θ ← θ − η∇L"],
                "first_anchor": "12:04",
            },
            {
                "name": "学习率",
                "en": "Learning Rate",
                "one_liner": "步长超参数。",
                "detail": "",
                "points": ["过大震荡"],
                "first_anchor": "12:10",
            },
        ],
    }


def test_paths():
    assert course_folder_name("IS5113") == "课堂-IS5113"
    assert lecture_stem(3, "梯度下降") == "第3节-梯度下降"
    print("PASS paths")


def test_render_lecture_has_index():
    md = render_lecture(_meta(Path("/tmp")), _draft())
    assert "## 本课知识点" in md
    assert "[[梯度下降]] — 这节讲了更新公式" in md
    assert "## 更新公式" in md
    assert "type: lesson" in md
    assert "术语表" not in md
    print("PASS render_lecture_has_index")


def test_write_and_upsert(tmp=None):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        meta = _meta(root)
        r1 = write_vault(meta, _draft())
        assert r1.lecture_path == root / "01-章节笔记" / "课堂-IS5113" / "第3节-梯度下降.md"
        assert r1.lecture_path.exists()
        assert len(r1.created_concepts) == 2
        gd = root / "02-概念卡片" / "梯度下降.md"
        original = gd.read_text(encoding="utf-8")
        assert "沿梯度反方向走。" in original
        assert "type: concept" in original
        moc = (root / "01-章节笔记" / "课堂-IS5113" / "_概览.md").read_text(encoding="utf-8")
        assert "[[第3节-梯度下降]]" in moc
        assert "[[梯度下降]]" in moc

        # 第二次：不覆盖一句话，追加出现位置
        draft2 = _draft()
        draft2["concepts"][0]["one_liner"] = "【错误的新一句话，不该写入】"
        draft2["concepts"][0]["points"] = ["学习率要调"]
        draft2["short_title"] = "梯度下降续"
        meta2 = _meta(root)
        meta2.lecture_n = 4
        r2 = write_vault(meta2, draft2)
        assert len(r2.updated_concepts) >= 1
        text = gd.read_text(encoding="utf-8")
        assert "沿梯度反方向走。" in text
        assert "错误的新一句话" not in text
        assert "学习率要调" in text
        assert "第4节-梯度下降续" in text
        # 出现位置带时间戳时，相关笔记仍应单独有一条 wikilink
        assert re.search(r"(?m)^- \[\[第4节-梯度下降续\]\]\s*$", text)
        print("PASS write_and_upsert")


def test_inspect_new_vs_merge():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        meta = _meta(root)
        rows = inspect_concepts(meta, _draft())
        assert all(r["action"] == "新建" for r in rows)
        write_vault(meta, _draft())
        rows2 = inspect_concepts(meta, _draft())
        assert all(r["action"] == "合并" for r in rows2)
        print("PASS inspect_new_vs_merge")


def test_inspect_does_not_create_dirs():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        meta = _meta(root)
        inspect_concepts(meta, _draft())
        assert not (root / "02-概念卡片").exists()
        assert not (root / "01-章节笔记").exists()
        print("PASS inspect_does_not_create_dirs")


def test_reuse_lecture_path():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        meta = _meta(root)
        r1 = write_vault(meta, _draft())
        old = r1.lecture_path
        draft = _draft()
        draft["short_title"] = "完全不同"
        r2 = write_vault(meta, draft, lecture_path=old)
        assert r2.lecture_path == old
        assert not (old.parent / "第3节-完全不同.md").exists()
        print("PASS reuse_lecture_path")


def test_session_remembers_note_path():
    from app.storage import Store
    with tempfile.TemporaryDirectory() as td:
        store = Store(Path(td) / "t.db")
        sid = store.create_session("t")
        assert store.get_note_path(sid) is None
        store.set_note_path(sid, "/tmp/第3节-梯度下降.md")
        assert store.get_note_path(sid) == "/tmp/第3节-梯度下降.md"
        print("PASS session_remembers_note_path")


def test_find_by_frontmatter_title():
    with tempfile.TemporaryDirectory() as td:
        cdir = Path(td)
        p = cdir / "Attention.md"
        p.write_text("---\ntitle: 注意力机制\ntype: concept\n---\n# 注意力\n", encoding="utf-8")
        found = find_concept_path(cdir, "注意力机制", "Attention")
        assert found == p
        print("PASS find_by_frontmatter_title")


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
