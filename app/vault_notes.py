"""把 NoteAgent 的 JSON 草稿写成 Obsidian 课节页 + 概念卡 + 课程概览。

课节页：01-章节笔记/课堂-{code}/第N节-{短标题}.md
概念卡：02-概念卡片/{中文名}.md（已有则只追加，不覆盖「一句话」）
概览：同课程目录 _概览.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app import settings as app_settings


def safe_filename(name: str, fallback: str = "未命名") -> str:
    name = re.sub(r'[\\/:*?"<>|]', "", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:40] if name else fallback)


def course_folder_name(code: str | None, _name: str | None = None) -> str:
    code = (code or "").strip()
    return f"课堂-{code}" if code else "课堂-未分类"


def lecture_stem(n: int, short_title: str) -> str:
    return f"第{n}节-{safe_filename(short_title, '课堂实录')}"


def yaml_escape(s: str) -> str:
    s = (s or "").replace('"', '\\"')
    return s


@dataclass
class VaultMeta:
    vault: Path
    notes_subdir: str
    concepts_subdir: str
    course_code: str
    course_name: str
    session_id: int
    lecture_n: int
    created: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))


@dataclass
class WriteResult:
    lecture_path: Path
    moc_path: Path
    created_concepts: list[Path]
    updated_concepts: list[Path]


def lecture_dir(meta: VaultMeta) -> Path:
    return meta.vault / meta.notes_subdir / course_folder_name(meta.course_code)


def concepts_dir(meta: VaultMeta) -> Path:
    return meta.vault / meta.concepts_subdir


def render_lecture(meta: VaultMeta, draft: dict) -> str:
    """渲染课节页全文（含 frontmatter）。"""
    n = meta.lecture_n
    short = safe_filename(draft.get("short_title") or "课堂实录")
    title = f"第{n}节 · {short}"
    code = (meta.course_code or "uncat").strip() or "uncat"
    lines = [
        "---",
        f'title: "{yaml_escape(title)}"',
        "type: lesson",
        f'course: "{yaml_escape(meta.course_name)}"',
        f"session: {meta.session_id}",
        f"lecture: {n}",
        f"tags: [lecture, {code}]",
        "source: live-subtitle",
        f"created: {meta.created}",
        "---",
        "",
        f"# {title}",
        "",
        "## 一句话核心",
        "",
        (draft.get("one_liner") or "（无）").strip(),
        "",
        "## 本课知识点",
        "",
    ]
    index = draft.get("knowledge_index") or []
    if not index:
        lines.append("（本课没有可单独复习的概念）")
        lines.append("")
    else:
        for item in index:
            name = item.get("name") or ""
            note = (item.get("note") or "").strip()
            if note:
                lines.append(f"- [[{name}]] — {note}")
            else:
                lines.append(f"- [[{name}]]")
        lines.append("")
    for sec in draft.get("sections") or []:
        title_s = (sec.get("title") or "补充").strip()
        body = (sec.get("markdown") or "").strip()
        lines.append(f"## {title_s}")
        lines.append("")
        if body:
            lines.append(body)
            lines.append("")
    hw = draft.get("homework") or []
    qs = draft.get("questions") or []
    if hw or qs:
        lines.append("## 这节的作业 / 疑问")
        lines.append("")
        if hw:
            for x in hw:
                lines.append(f"- {x}")
            lines.append("")
        if qs:
            for x in qs:
                lines.append(f"- {x}")
            lines.append("")
    anchors = draft.get("anchors") or []
    if anchors:
        lines.append("## 回听锚点")
        lines.append("")
        for a in anchors:
            t = a.get("t") or "--:--"
            quote = (a.get("quote") or "").strip()
            lines.append(f"- [{t}] {quote}")
        lines.append("")
    wiki = lecture_stem(n, draft.get("short_title") or "课堂实录")
    lines.append("## 相关")
    lines.append("")
    lines.append(f"- session {meta.session_id}")
    for item in index:
        name = item.get("name")
        if name:
            lines.append(f"- [[{name}]]")
    if not index:
        lines.append(f"- [[{wiki}]]")
    lines.append("")
    return "\n".join(lines)


def _frontmatter_title(text: str) -> str:
    m = re.search(r"(?m)^title:\s*\"?([^\"\n]+)\"?\s*$", text[:800])
    return (m.group(1).strip() if m else "")


def find_concept_path(cdir: Path, name: str, en: str = "") -> Path:
    """已有卡：同名文件或 frontmatter title 匹配；否则新路径。不创建目录。"""
    exact = cdir / f"{safe_filename(name)}.md"
    if not cdir.is_dir():
        return exact
    if exact.exists():
        return exact
    name_l = name.lower()
    en_l = (en or "").lower()
    for p in sorted(cdir.glob("*.md")):
        try:
            head = p.read_text(encoding="utf-8")[:1000]
        except OSError:
            continue
        title = _frontmatter_title(head)
        if title == name or title.lower() == name_l:
            return p
        if en_l and en_l in head[:600].lower() and "type: concept" in head:
            if f"aliases:" in head and en in head:
                return p
    return exact


def _insert_after_heading(text: str, heading: str, bullet: str) -> str:
    """在 `## heading` 后追加一条 bullet；没有该标题则在文末加一节。

    用整行匹配去重，避免「- [[课节]]」被「- [[课节]] · 12:04」误伤。
    """
    line = bullet.strip()
    if re.search(rf"(?m)^{re.escape(line)}\s*$", text):
        return text
    pat = re.compile(rf"(^## {re.escape(heading)}\s*\n)", re.M)
    m = pat.search(text)
    if m:
        return text[:m.end()] + "\n" + bullet + "\n" + text[m.end():]
    extra = f"\n## {heading}\n\n{bullet}\n"
    return text.rstrip() + extra + "\n"


def render_new_concept(concept: dict, lecture_wiki: str, created: str) -> str:
    name = concept.get("name") or "未命名"
    en = concept.get("en") or ""
    fm_alias = f'aliases: ["{yaml_escape(en)}"]\n' if en else ""
    points = concept.get("points") or []
    point_lines = "\n".join(f"- {p}" for p in points) if points else "- （待补）"
    anchor = (concept.get("first_anchor") or "").strip()
    appear = f"- [[{lecture_wiki}]]"
    if anchor:
        appear += f" · {anchor}"
    detail = (concept.get("detail") or "").strip() or "（待补）"
    one = (concept.get("one_liner") or "").strip() or "（待补）"
    return (
        f"---\n"
        f'title: "{yaml_escape(name)}"\n'
        f"type: concept\n"
        f"{fm_alias}"
        f"tags: [concept, lecture]\n"
        f"created: {created}\n"
        f"source: live-subtitle\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"## 一句话\n\n"
        f"{one}\n\n"
        f"## 详解\n\n"
        f"{detail}\n\n"
        f"## 关键点\n\n"
        f"{point_lines}\n\n"
        f"## 出现位置\n\n"
        f"{appear}\n\n"
        f"## 相关笔记\n\n"
        f"- [[{lecture_wiki}]]\n"
    )


def upsert_concept(path: Path, concept: dict, lecture_wiki: str, created: str) -> str:
    """new 或 merge。返回 'created' / 'updated'。"""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_new_concept(concept, lecture_wiki, created), encoding="utf-8")
        return "created"
    text = path.read_text(encoding="utf-8")
    appear = f"- [[{lecture_wiki}]]"
    anchor = (concept.get("first_anchor") or "").strip()
    appear_line = appear + (f" · {anchor}" if anchor else "")
    text = _insert_after_heading(text, "出现位置", appear_line)
    for p in concept.get("points") or []:
        if p:
            text = _insert_after_heading(text, "关键点", f"- {p}")
    rel_heading = "相关笔记" if "## 相关笔记" in text else ("相关" if re.search(r"^## 相关\s*$", text, re.M) else "相关笔记")
    text = _insert_after_heading(text, rel_heading, appear)
    path.write_text(text, encoding="utf-8")
    return "updated"


def _ensure_moc(path: Path, meta: VaultMeta) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    code = (meta.course_code or "uncat").strip() or "uncat"
    return (
        f"---\n"
        f'title: "{yaml_escape(meta.course_name)} 课堂笔记"\n'
        f"type: chapter\n"
        f"tags: [lecture, moc, {code}]\n"
        f"source: live-subtitle\n"
        f"created: {meta.created}\n"
        f"---\n\n"
        f"# {meta.course_name}\n\n"
        f"## 课节\n\n"
        f"## 关键概念\n\n"
    )


def update_moc(path: Path, meta: VaultMeta, lecture_wiki: str, concept_names: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _ensure_moc(path, meta)
    lecture_bullet = f"- [[{lecture_wiki}]]"
    if lecture_bullet not in text:
        text = _insert_after_heading(text, "课节", lecture_bullet)
    for name in concept_names:
        bullet = f"- [[{name}]]"
        if name and bullet not in text:
            text = _insert_after_heading(text, "关键概念", bullet)
    path.write_text(text, encoding="utf-8")


def inspect_concepts(meta: VaultMeta, draft: dict) -> list[dict]:
    """预览用：每张卡是新建还是合并。"""
    cdir = concepts_dir(meta)
    rows = []
    for c in draft.get("concepts") or []:
        name = c.get("name") or ""
        path = find_concept_path(cdir, name, c.get("en") or "")
        rows.append({
            "name": name,
            "en": c.get("en") or "",
            "one_liner": c.get("one_liner") or "",
            "path": path,
            "action": "合并" if path.exists() else "新建",
        })
    return rows


def write_vault(meta: VaultMeta, draft: dict, lecture_markdown: str | None = None,
                lecture_path: Path | None = None) -> WriteResult:
    """写入课节页、upsert 概念卡、更新概览。lecture_path 已存在则覆盖该文件。"""
    ldir = lecture_dir(meta)
    ldir.mkdir(parents=True, exist_ok=True)
    stem = lecture_stem(meta.lecture_n, draft.get("short_title") or "课堂实录")
    if lecture_path is not None and not lecture_path.exists():
        lecture_path = None
    path = lecture_path or (ldir / f"{stem}.md")
    md = lecture_markdown if lecture_markdown is not None else render_lecture(meta, draft)
    path.write_text(md if md.endswith("\n") else md + "\n", encoding="utf-8")

    wiki = path.stem
    created, updated = [], []
    cdir = concepts_dir(meta)
    for c in draft.get("concepts") or []:
        cp = find_concept_path(cdir, c.get("name") or "", c.get("en") or "")
        kind = upsert_concept(cp, c, wiki, meta.created)
        if kind == "created":
            created.append(cp)
        else:
            updated.append(cp)

    moc = ldir / "_概览.md"
    names = [c.get("name") for c in (draft.get("concepts") or []) if c.get("name")]
    update_moc(moc, meta, wiki, names)
    return WriteResult(path, moc, created, updated)


def meta_from_settings(course_code: str, course_name: str, session_id: int,
                       lecture_n: int, vault: str | None = None) -> VaultMeta:
    s = app_settings.load()
    raw = vault if vault is not None else s.get("vault")
    if not (raw or "").strip():
        from app import config
        root = config.EXPORT_DIR / "notes"
    else:
        root = Path(raw)
    return VaultMeta(
        vault=root,
        notes_subdir=s.get("notes_subdir") or "01-章节笔记",
        concepts_subdir=s.get("concepts_subdir") or "02-概念卡片",
        course_code=course_code or "",
        course_name=course_name or "课堂实录",
        session_id=session_id,
        lecture_n=lecture_n,
    )
