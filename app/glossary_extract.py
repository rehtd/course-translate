"""课后从英中对照提取术语候选。用户确认后才写入课程术语表。

课上逐句译文、以及以后的全量精翻，都走同一套提取：不在录制中改表。
"""
from __future__ import annotations

import json
import urllib.request

from app import config
from app.note_agent import extract_json

EXTRACT_SYSTEM = """你是研究生课堂的术语编辑。输入是老师讲课的英中对照（课上逐句翻译或课后精翻）。

任务：列出「下次上课必须统一译法」的术语。只要：
- 专有名词（人名、学校、课程名、软件/数据集名）
- 本课反复出现的技术词、方法名
不要：日常口语、完整句子、一次性例子里的普通词。
不要编造输入里没出现的英文；中文译名优先用对照里已经用过的。

只输出 JSON 对象：
{"terms": [{"en": "English term", "zh": "中文", "reason": "人名/课名/方法"}]}
最多 16 条。没有则 terms 为空数组。
"""

_CHUNK_CHARS = 9000


def pairs_from_segments(rows) -> list[tuple[str, str]]:
    """list_segments 行 → 可用的英中对照。"""
    out = []
    for row in rows or []:
        if len(row) < 5:
            continue
        en = (row[3] or "").strip().replace("\n", " ")
        zh = (row[4] or "").strip().replace("\n", " ")
        if not en or en.startswith("[ASR错误]"):
            continue
        if not zh or zh.startswith("[翻译失败]") or zh.startswith("（未识别"):
            continue
        out.append((en, zh))
    return out


def format_pairs(pairs) -> str:
    lines = []
    for en, zh in pairs:
        lines.append(f"EN: {en}")
        lines.append(f"ZH: {zh}")
    return "\n".join(lines)


def chunk_pairs(pairs, max_chars: int = _CHUNK_CHARS) -> list[list[tuple[str, str]]]:
    if not pairs:
        return []
    chunks, buf, n = [], [], 0
    for en, zh in pairs:
        line = f"EN: {en}\nZH: {zh}\n"
        if n + len(line) > max_chars and buf:
            chunks.append(buf)
            buf, n = [(en, zh)], len(line)
        else:
            buf.append((en, zh))
            n += len(line)
    if buf:
        chunks.append(buf)
    return chunks


def normalize_candidates(raw) -> list[dict]:
    terms = []
    if isinstance(raw, dict):
        items = raw.get("terms") or raw.get("glossary") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    seen = set()
    for item in items:
        if isinstance(item, str) and "=" in item:
            en, zh = item.split("=", 1)
            reason = ""
        elif isinstance(item, dict):
            en = str(item.get("en") or item.get("en_term") or "").strip()
            zh = str(item.get("zh") or item.get("zh_term") or "").strip()
            reason = str(item.get("reason") or "").strip()
        else:
            continue
        en, zh = en.strip(), zh.strip()
        if not en or not zh or len(en) > 80 or len(zh) > 40:
            continue
        key = en.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append({"en": en, "zh": zh, "reason": reason})
    return terms


def classify_candidates(candidates, existing) -> list[dict]:
    """对照已有术语表：新建 / 已有 / 改译。"""
    by_en = {str(e).lower(): (e, z) for e, z in (existing or [])}
    out = []
    for c in candidates:
        en, zh = c["en"], c["zh"]
        key = en.lower()
        if key not in by_en:
            action, old_zh = "新建", ""
        elif by_en[key][1] == zh:
            action, old_zh = "已有", zh
        else:
            action, old_zh = "改译", by_en[key][1]
        out.append({
            "en": en, "zh": zh, "reason": c.get("reason") or "",
            "action": action, "old_zh": old_zh,
        })
    return out


def _complete(system: str, user: str, timeout: int = 90) -> str:
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 2048,
        "temperature": 0.2,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"}
    url = f"{config.DEEPSEEK_BASE_URL}/chat/completions"
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        payload.pop("response_format", None)
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def extract_candidates(pairs, existing=None) -> list[dict]:
    """DeepSeek 提取 + 与已有表分类。"""
    existing = list(existing or [])
    if not pairs:
        return []
    exist_txt = "\n".join(f"- {e} = {z}" for e, z in existing) or "（空）"
    found = []
    for i, chunk in enumerate(chunk_pairs(pairs), 1):
        user = (
            f"已有术语表：\n{exist_txt}\n\n"
            f"第 {i} 段英中对照：\n{format_pairs(chunk)}"
        )
        raw = extract_json(_complete(EXTRACT_SYSTEM, user))
        found.extend(normalize_candidates(raw))
    merged, seen = [], set()
    for c in found:
        key = c["en"].lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
    return classify_candidates(merged, existing)
