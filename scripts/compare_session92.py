"""session 92 三向对比：标准原文(离线全量) vs 实时转写(DB) vs 译文。

回答用户问题「字幕里的多词是哪来的」：
1. ASR 层：实时转写(segments.raw_text) vs 标准原文(offline JSON)
   → 找「实时多出的实义词」= ASR 脑补/幻觉；「标准有实时无」= 漏听
2. 翻译层：译文 vs 实时转写（译文是否忠实于转写，不引入额外内容）
3. 输出逐句对照抽样 + 统计报告

运行: <venv>/bin/python scripts/compare_session92.py
"""
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/subtitle.db"
OFFLINE = ROOT / "data/exports/session_92_offline_small.json"
SESSION_ID = 92
STOP = set("""a an the and or but if then of to in on at for with from by as is are was were be been
it its this that these those we you they he she i i'm we're you're they're there here what which who
whom so because do does did done have has had not no yes ok okay now well just really very so like
um uh actually mean means meant let let's can could will would should may might shall must about
into over under out up down all any some more most such only own same other new than per via
also too bit lots lot stuff things thing way ways one two """.split())


def clean(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9']+", " ", (s or "").lower()).strip()


def load_offline() -> list:
    return json.loads(OFFLINE.read_text(encoding="utf-8"))


def load_realtime(sid: int) -> tuple[list, float]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    s = con.execute("SELECT started_at FROM sessions WHERE id=?", (sid,)).fetchone()
    segs = con.execute(
        "SELECT t_start, t_end, raw_text, translated_text FROM segments "
        "WHERE session_id=? AND raw_text IS NOT NULL AND TRIM(raw_text)!='' "
        "ORDER BY t_start", (sid,)).fetchall()
    con.close()
    start_epoch = datetime.fromisoformat(s["started_at"]).timestamp()
    return segs, start_epoch


def overlap(a0, a1, b0, b1) -> float:
    """两区间重叠秒数。"""
    return max(0.0, min(a1, b1) - max(a0, b0))


def ref_for(seg, off, start_epoch) -> str:
    """实时段的参考原文：覆盖其 wav 时间范围的所有离线段文本拼接。"""
    w0 = seg["t_start"] - start_epoch
    w1 = seg["t_end"] - start_epoch
    parts = []
    for o in off:
        if overlap(w0, w1, o["start"], o["end"]) > 0:
            parts.append(o["text"])
    return " ".join(parts)


def words(s: str) -> Counter:
    return Counter(clean(s).split())


def main():
    off = load_offline()
    segs, start_epoch = load_realtime(SESSION_ID)
    print(f"离线标准原文: {len(off)} 段 | 实时转写: {len(segs)} 段")

    extra_all = Counter()   # 实时多出的词（标准原文没有）
    missing_all = Counter()  # 标准原文有、实时没有
    n_seg = 0
    examples = []           # (类型, 实时句, 参考句, 词)
    for seg in segs:
        ref = ref_for(seg, off, start_epoch)
        if not ref.strip():
            continue
        n_seg += 1
        w_rt = words(seg["raw_text"])
        w_ref = words(ref)
        # 实时有而参考没有的词（过滤停用词 + 数字/单个字母）
        extra = {w: c for w, c in (w_rt - w_ref).items()
                 if w not in STOP and len(w) > 1 and not w.isdigit()}
        # 参考有而实时没有
        missing = {w: c for w, c in (w_ref - w_rt).items()
                   if w not in STOP and len(w) > 1 and not w.isdigit()}
        extra_all.update(extra)
        missing_all.update(missing)
        if extra and len(examples) < 8:
            examples.append(("ASR多词", seg["raw_text"], ref, " | ".join(sorted(extra))))

    tot_rt = sum(len(words(s["raw_text"])) for s in segs)
    tot_ref = sum(len(words(s["text"])) for s in off)
    n_extra = sum(extra_all.values())
    n_missing = sum(missing_all.values())
    print(f"\n=== ASR 层统计（对齐 {n_seg} 段）===")
    print(f"实时总词数: {tot_rt} | 标准原文总词数: {tot_ref}")
    print(f"ASR 多出的实义词（幻觉候选）: {n_extra} 次 / {len(extra_all)} 个不同词")
    print(f"ASR 漏听的实义词: {n_missing} 次 / {len(missing_all)} 个不同词")
    print(f"幻觉密度: {n_extra/max(tot_rt,1)*100:.2f}%（每百词多出的词）")

    print("\n=== 幻觉词 Top 20（实时多出且标准原文没有）===")
    for w, c in extra_all.most_common(20):
        print(f"  {w:24s} x{c}")

    print("\n=== 漏听词 Top 15（标准原文有、实时没有）===")
    for w, c in missing_all.most_common(15):
        print(f"  {w:24s} x{c}")

    print("\n=== ASR 多词示例（前 8 段）===")
    for kind, rt, ref, wl in examples:
        print(f"  [{kind}] 实时: {rt[:100]}")
        print(f"          参考: {ref[:100]}")
        print(f"          多出: {wl}")
        print()

    # 翻译层抽样：译文 vs 标准原文（展示用户感知的"字幕多词"）
    print("=== 翻译层抽样（译文 vs 标准原文，找翻译放大/幻觉）===")
    shown = 0
    for seg in segs[:120]:
        ref = ref_for(seg, off, start_epoch)
        zh = seg["translated_text"] or ""
        if not ref.strip() or not zh.strip():
            continue
        # 译文里出现"不应有的具体信息"无法自动判定，抽样展示前 6 段供人工复核
        if shown < 6:
            print(f"  实时: {seg['raw_text'][:90]}")
            print(f"  译文: {zh[:90]}")
            print(f"  原文: {ref[:90]}")
            print()
            shown += 1

    out = ROOT / "data/exports/session_92_对比报告.md"
    out.write_text(
        f"# session 92 三向对比报告\n\n"
        f"- 标准原文（离线全量转写 small+VAD）: {len(off)} 段 / {tot_ref} 词\n"
        f"- 实时转写（DB segments）: {len(segs)} 段 / {tot_rt} 词\n"
        f"- 对齐段数: {n_seg}\n\n"
        f"## ASR 层\n- 多出实义词（幻觉候选）: {n_extra} 次 / {len(extra_all)} 个\n"
        f"- 漏听实义词: {n_missing} 次 / {len(missing_all)} 个\n"
        f"- 幻觉密度: {n_extra/max(tot_rt,1)*100:.2f}%\n\n"
        f"### 幻觉词 Top20\n" +
        "\n".join(f"- {w} x{c}" for w, c in extra_all.most_common(20)) +
        f"\n\n### 漏听词 Top15\n" +
        "\n".join(f"- {w} x{c}" for w, c in missing_all.most_common(15)) +
        "\n", encoding="utf-8")
    print(f"[报告已存] {out}")


if __name__ == "__main__":
    main()
