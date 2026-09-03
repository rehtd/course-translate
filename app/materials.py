"""课件 PDF：复制到 data/materials，抽取文字给笔记 Agent。"""
from __future__ import annotations

import shutil
from pathlib import Path


def save_pdf(src: str | Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def extract_pdf_text(path: str | Path, max_chars: int = 12000) -> str:
    """抽出 PDF 文本；扫描件/加密则返回空串。"""
    path = Path(path)
    if not path.is_file():
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:  # noqa: BLE001
        return ""
    parts = []
    n = 0
    for page in reader.pages:
        try:
            t = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            t = ""
        if not t:
            continue
        parts.append(t)
        n += len(t)
        if n >= max_chars:
            break
    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（课件摘录已截断）"
    return text
