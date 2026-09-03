"""笔记 Agent：转写 → JSON 契约（课节页骨架 + 概念卡），由 vault_notes 落库。

课节页：一句话核心 + 本课知识点（硬性）+ Agent 自拟章节。
概念卡：跨课累积，程序 upsert，模型不直接改已有 Markdown。
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime

from app import config
from app.storage import Store

_CHUNK_CHARS = 12000

SYSTEM_PROMPT = """你是研究生课程「{course}」的笔记整理 Agent。输入是课堂英文转写（相对开课的 [mm:ss] + 原文，以及用户打点）。

先分辨三类，只根据课堂内容产出 JSON（不要寒暄、设备调试、ASR 胡话；不要「已忽略」清单）：
- 课堂内容：知识、方法、案例、公式、作业、答疑 → 保留
- 无用信息：寒暄、课堂管理、闲聊 → 丢弃
- 误入内容：识别错误、噪音误转写 → 丢弃

输出必须是一个 JSON 对象，不要 Markdown 围栏，不要解说。字段：
{{
  "short_title": "本课短标题，3~12 字，用作文件名，不要带第N节",
  "one_liner": "一句话核心（中文）",
  "knowledge_index": [{{"name": "概念中文名", "note": "这节新讲了什么（可空）"}}],
  "sections": [{{"title": "自拟小标题", "markdown": "中文正文，可含列表"}}],
  "homework": ["作业/截止日期，没有则空数组"],
  "questions": ["存疑或打点处值得追问的，没有则空数组"],
  "anchors": [{{"t": "mm:ss", "quote": "金句或关键推导（中文简述）"}}],
  "concepts": [{{
    "name": "与 knowledge_index 一致的中文名",
    "en": "English term",
    "one_liner": "一句话定义",
    "detail": "稍详的解释（一段）",
    "points": ["关键点1", "关键点2"],
    "first_anchor": "mm:ss"
  }}]
}}

硬性规则：
- knowledge_index 不能空（除非整课没有可复习的概念）；每条 name 必须在 concepts 里有对应卡。
- sections 的 title 按这节课实际内容自拟，不要用「本课摘要」「术语表」「知识要点」「已忽略内容」这种固定标题。
- 细节、定义、公式放在 concepts；sections 只组织「这节怎么讲的 / 例子 / 对比」。
- 一次性事务（作业截止、点名）进 homework，不要建概念卡。
- 只根据转写，不编造没讲的内容；术语中英并存；不确定写「存疑」。
- anchors 3~8 条；时间用输入里的相对时间戳。
- 全部中文撰写（专有名词可保留英文）。
"""

CHUNK_PROMPT = """你在处理长课的第 {i}/{n} 段转写。只根据本段输出 JSON（不要围栏）：
{{
  "knowledge_index": [{{"name": "...", "note": "..."}}],
  "sections": [{{"title": "...", "markdown": "..."}}],
  "homework": [],
  "questions": [],
  "anchors": [{{"t": "mm:ss", "quote": "..."}}],
  "concepts": [{{"name": "...", "en": "...", "one_liner": "...", "detail": "...", "points": [], "first_anchor": "mm:ss"}}]
}}
规则同系统说明：不编造；作业进 homework；本段没有可复习概念则 knowledge_index 和 concepts 为空数组。
"""

MERGE_PROMPT = """下面是同一节课若干分段的 JSON 数组。去重合并为一份完整课节 JSON，字段与系统说明相同（short_title、one_liner、knowledge_index、sections、homework、questions、anchors、concepts）。
- concepts 按中文 name 去重，要点合并，保留最早 first_anchor。
- knowledge_index 保持课堂出现顺序，去重。
- sections 按时间/主题整理，不要用固定的「摘要/术语表」标题。
只输出一个 JSON 对象。
"""


def empty_draft(short_title: str = "课堂实录") -> dict:
    return {
        "short_title": short_title,
        "one_liner": "（本次录音没有可整理的内容）",
        "knowledge_index": [],
        "sections": [],
        "homework": [],
        "questions": [],
        "anchors": [],
        "concepts": [],
    }


def extract_json(text: str) -> dict:
    """从模型输出里抽出 JSON 对象。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("笔记 Agent 未返回 JSON 对象")
    return json.loads(text[i:j + 1])


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _as_str(v) -> str:
    return ("" if v is None else str(v)).strip()


def normalize_draft(raw: dict | None, fallback_title: str = "课堂实录") -> dict:
    """把模型 JSON 收成稳定结构。"""
    raw = raw if isinstance(raw, dict) else {}
    lec = raw.get("lecture") if isinstance(raw.get("lecture"), dict) else raw
    short = _as_str(lec.get("short_title") or raw.get("short_title")) or fallback_title
    index = []
    for item in _as_list(raw.get("knowledge_index") or lec.get("knowledge_index")):
        if isinstance(item, str) and item.strip():
            index.append({"name": item.strip(), "note": ""})
        elif isinstance(item, dict) and _as_str(item.get("name")):
            index.append({"name": _as_str(item.get("name")), "note": _as_str(item.get("note"))})
    sections = []
    for sec in _as_list(raw.get("sections") or lec.get("sections")):
        if isinstance(sec, dict) and (_as_str(sec.get("title")) or _as_str(sec.get("markdown"))):
            sections.append({
                "title": _as_str(sec.get("title")) or "补充",
                "markdown": _as_str(sec.get("markdown")),
            })
    concepts = []
    seen = set()
    for c in _as_list(raw.get("concepts")):
        if not isinstance(c, dict):
            continue
        name = _as_str(c.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        concepts.append({
            "name": name,
            "en": _as_str(c.get("en")),
            "one_liner": _as_str(c.get("one_liner")),
            "detail": _as_str(c.get("detail")),
            "points": [_as_str(p) for p in _as_list(c.get("points")) if _as_str(p)],
            "first_anchor": _as_str(c.get("first_anchor")),
        })
    by_name = {c["name"]: c for c in concepts}
    for item in index:
        if item["name"] not in by_name:
            concepts.append({
                "name": item["name"], "en": "", "one_liner": item.get("note") or "",
                "detail": "", "points": [], "first_anchor": "",
            })
            by_name[item["name"]] = concepts[-1]
    if not index and concepts:
        index = [{"name": c["name"], "note": ""} for c in concepts]
    return {
        "short_title": short[:40],
        "one_liner": _as_str(lec.get("one_liner") or raw.get("one_liner")),
        "knowledge_index": index,
        "sections": sections,
        "homework": [_as_str(x) for x in _as_list(raw.get("homework") or lec.get("homework")) if _as_str(x)],
        "questions": [_as_str(x) for x in _as_list(raw.get("questions") or lec.get("questions")) if _as_str(x)],
        "anchors": [
            {"t": _as_str(a.get("t")), "quote": _as_str(a.get("quote"))}
            for a in _as_list(raw.get("anchors") or lec.get("anchors"))
            if isinstance(a, dict) and (_as_str(a.get("t")) or _as_str(a.get("quote")))
        ],
        "concepts": concepts,
    }


def rel_timestamp(t0: float, origin: float) -> str:
    """墙钟秒 → 相对开课 mm:ss（超过 1 小时 h:mm:ss）。"""
    sec = max(0, int(t0 - origin))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def split_transcript(text: str, max_chars: int = _CHUNK_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    lines = text.splitlines(keepends=True)
    chunks, buf, n = [], [], 0
    for line in lines:
        if n + len(line) > max_chars and buf:
            chunks.append("".join(buf).strip())
            buf, n = [line], len(line)
        else:
            buf.append(line)
            n += len(line)
    if buf:
        chunks.append("".join(buf).strip())
    return [c for c in chunks if c]


class NoteAgent:
    def __init__(self, store=None, api_key=None, base_url=None, model=None, timeout=180):
        self.store = store or Store()
        self.api_key = api_key or config.DEEPSEEK_API_KEY
        self.base_url = base_url or config.DEEPSEEK_BASE_URL
        self.model = model or config.DEEPSEEK_MODEL
        self.timeout = timeout

    def build_input(self, sid: int) -> str:
        """相对开课时间戳的转写；跳过 ASR 失败行与暂停标记。"""
        sess = self.store.get_session(sid)
        origin = None
        if sess and sess[3]:
            try:
                origin = datetime.fromisoformat(sess[3]).timestamp()
            except (TypeError, ValueError):
                origin = None
        rows = self.store.list_segments(sid)
        if origin is None and rows:
            origin = rows[0][1] or 0.0
        origin = origin or 0.0
        events = []
        for _seq, t0, _t1, en, _zh in rows:
            en = (en or "").strip().replace("\n", " ")
            if not en or en.startswith("[ASR错误]"):
                continue
            ts = t0 if t0 is not None else origin
            events.append((ts, f"[{rel_timestamp(ts, origin)}] {en}"))
        for t, kind, note in self.store.list_markers(sid):
            if kind == "pause":
                continue
            events.append((t, f"[{rel_timestamp(t, origin)}] ⭐ {note or '重点/疑问'}"))
        events.sort(key=lambda x: x[0])
        return "\n".join(e[1] for e in events)

    def _complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:
            payload.pop("response_format", None)
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"].strip()

    def generate_note(self, sid: int, course: str = "课堂实录",
                      title: str | None = None) -> dict:
        """返回 normalize 后的笔记草稿 dict（不是 Markdown）。"""
        fallback = (title or "课堂实录").strip() or "课堂实录"
        transcript = self.build_input(sid)
        if not transcript.strip():
            return empty_draft(fallback)
        system = SYSTEM_PROMPT.format(course=course)
        chunks = split_transcript(transcript)
        if len(chunks) == 1:
            raw = extract_json(self._complete(
                system,
                f"课堂转写如下（相对开课时间 + 英文原文）：\n\n{chunks[0]}"))
            return normalize_draft(raw, fallback)
        partials = []
        n = len(chunks)
        for i, ch in enumerate(chunks, 1):
            raw = extract_json(self._complete(
                system + "\n" + CHUNK_PROMPT.format(i=i, n=n),
                f"本段转写：\n\n{ch}",
                max_tokens=4096))
            partials.append(normalize_draft(raw, fallback))
        merged = extract_json(self._complete(
            system + "\n" + MERGE_PROMPT,
            json.dumps(partials, ensure_ascii=False, indent=2)))
        out = normalize_draft(merged, fallback)
        if not out["short_title"] or out["short_title"] == "课堂实录":
            out["short_title"] = fallback
        return out
