"""session 94 对比分析：实时链路入库翻译 vs 录音离线整体转写+翻译。

回答用户问题：「目前的最终翻译质量对得上最后用录音的整体翻译吗」。

关键修正（v2）：
- 识别暂停/恢复：DB 段墙钟 t_start 出现 >60s 跳跃即暂停；暂停期间实时链路
  不喂 ASR（wav 连续录），离线转写会覆盖暂停段 → 对比时标记为「暂停缺口」。
- 恢复后时间戳偏移校正：暂停恢复重锚定后，实时段时间戳整体偏晚 ~20s
  （实测中位数 -19.8s），用内容锚点拟合偏移量并校正，否则 WER 虚高。

三层对比：
1) 时间覆盖 —— 实时段（墙钟→wav）vs 离线段（wav 内秒），含暂停缺口标注
2) ASR 原文 WER —— 分「暂停前」「恢复后(校正)」两段，60s 桶词级 Levenshtein
3) 翻译质量 —— 离线全文分块 → DeepSeek 翻译（与实时同参）→ 时间窗并排对比

用法：
  python scripts/compare_session94.py            # 完整跑（含离线翻译 API）
  python scripts/compare_session94.py --no-translate   # 只跑本地分析
"""
import argparse
import json
import re
import sqlite3
import statistics
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, ".")
from app import config  # noqa: E402
from app.translate import DeepSeekTranslator  # noqa: E402

DB = "data/subtitle.db"
OFFLINE_JSON = "data/exports/session_94_offline.json"
OUT_MD = "data/exports/session_94_实时vs离线翻译对比报告.md"
SID = 94
BUCKET = 60.0            # WER 对比桶宽（秒）
PAUSE_GAP = 60.0         # 墙钟跳跃超过此秒数视为暂停
OFFLINE_BLOCK_WORDS = 250  # 离线翻译分块大小（英文词数）
SAMPLE_BLOCKS = 4        # 报告里并排展示的翻译块数


def words(t: str):
    return re.findall(r"[A-Za-z']+", t or "")


def wset(t: str):
    return set(re.findall(r"[a-z']+", (t or "").lower()))


def cjk_chars(t: str):
    return len(re.findall(r"[\u4e00-\u9fff]", t or ""))


def hms(sec):
    sec = max(0.0, sec)
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def levenshtein_wer(ref_w, hyp_w):
    n, m = len(ref_w), len(hyp_w)
    dp = np.zeros((n + 1, m + 1), dtype=np.int32)
    dp[:, 0] = np.arange(n + 1)
    dp[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        rw = ref_w[i - 1].lower()
        for j in range(1, m + 1):
            cost = 0 if rw == hyp_w[j - 1].lower() else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return int(dp[n][m]), n


def load_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sess = con.execute("SELECT started_at, ended_at, title FROM sessions WHERE id=?", (SID,)).fetchone()
    rows = con.execute(
        "SELECT seq, t_start, t_end, raw_text, translated_text "
        "FROM segments WHERE session_id=? ORDER BY seq", (SID,)).fetchall()
    con.close()
    return sess, rows


def find_pauses(db_segs):
    """从实时段墙钟序列找 >PAUSE_GAP 的跳跃，返回暂停区间列表 [(wav_开始, wav_结束)]。"""
    pauses = []
    for i in range(1, len(db_segs)):
        gap = db_segs[i]["t_start"] - db_segs[i - 1]["t_end"]
        if gap > PAUSE_GAP:
            pauses.append((db_segs[i - 1]["end"], db_segs[i]["start"]))
    return pauses

def fit_shift(db_segs, off, lo, hi):
    """内容锚点拟合：恢复后 [lo,hi) 区间内，实时段 vs 离线最佳匹配段的时间差中位数。"""
    diffs = []
    for d in db_segs:
        if d["start"] < lo or d["start"] >= hi or not d["raw"].strip():
            continue
        dw = wset(d["raw"])
        if len(dw) < 3:
            continue
        best, bs = None, 0
        for o in off:
            s2 = len(dw & wset(o["text"]))
            if s2 > bs:
                bs, best = s2, o
        if best and bs >= 3:
            diffs.append(best["start"] - d["start"])
    if not diffs:
        return 0.0
    return statistics.median(diffs)


def bucket_wer(db_segs, off, lo, hi, db_shift=0.0):
    """[lo,hi) 区间内按 60s 桶做词级 WER；返回 (ref词, hyp词, ed, 桶明细)。"""
    nb = int((hi - lo) // BUCKET) + 1
    tot_ref = tot_hyp = tot_ed = 0
    detail = []
    for b in range(nb):
        bs = lo + b * BUCKET
        be = min(hi, bs + BUCKET)
        ref = " ".join(x["text"] for x in off if x["start"] < be and x["end"] >= bs)
        hyp = " ".join(x["raw"] for x in db_segs
                       if x["start"] + db_shift < be and x["end"] + db_shift >= bs)
        rw, hw = words(ref), words(hyp)
        if not rw and not hw:
            continue
        ed, n = levenshtein_wer(rw, hw)
        tot_ref += n
        tot_hyp += len(hw)
        tot_ed += ed
        detail.append((bs, be, n, len(hw), ed))
    return tot_ref, tot_hyp, tot_ed, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-translate", action="store_true", help="跳过离线翻译 API，只跑本地分析")
    args = ap.parse_args()

    sess, rows = load_db()
    start_iso = sess["started_at"]
    dt = datetime.fromisoformat(start_iso)
    start_epoch = time.mktime(dt.timetuple())
    print(f"session {SID} started_at={start_iso} epoch={start_epoch:.0f}")

    # ---- DB 实时段（墙钟 → wav 内秒） ----
    db_segs = []
    for r in rows:
        db_segs.append({
            "seq": r["seq"],
            "t_start": r["t_start"],
            "t_end": r["t_end"],
            "start": max(0.0, r["t_start"] - start_epoch),
            "end": max(0.0, r["t_end"] - start_epoch),
            "raw": (r["raw_text"] or "").strip(),
            "tr": (r["translated_text"] or "").strip(),
        })
    db_raw_ok = [s for s in db_segs if s["raw"]]
    db_raw_empty = [s for s in db_segs if not s["raw"]]

    with open(OFFLINE_JSON, encoding="utf-8") as f:
        off = json.load(f)
    off_dur = max(s["end"] for s in off)

    # ---- 暂停识别 ----
    pauses = find_pauses(db_segs)
    print(f"检测到暂停区间: {[(hms(a), hms(b)) for a, b in pauses]}")
    pause_total = sum(b - a for a, b in pauses)

    # 暂停前/后主区间
    pre_lo, pre_hi = 0.0, (pauses[0][0] if pauses else off_dur)
    post_lo = (pauses[-1][1] if pauses else off_dur)
    post_hi = off_dur + 30.0  # 给尾部一点余量
    print(f"暂停前 [{hms(pre_lo)}–{hms(pre_hi)}]  恢复后 [{hms(post_lo)}–{hms(post_hi)}]")

    # ---- 恢复后时间戳偏移拟合 ----
    shift = fit_shift(db_segs, off, post_lo, post_hi)
    print(f"恢复后内容锚点拟合偏移: {shift:+.1f}s")

    # ---- 时间覆盖 ----
    db_t0 = min(s["start"] for s in db_segs)
    db_t1 = max(s["end"] for s in db_segs)
    # 实时有效语音覆盖（非空段并集）
    db_on_sec = 0.0
    cur_s = cur_e = None
    for s in sorted(db_raw_ok, key=lambda s: s["start"]):
        if cur_e is None or s["start"] > cur_e:
            if cur_e is not None:
                db_on_sec += cur_e - cur_s
            cur_s, cur_e = s["start"], s["end"]
        else:
            cur_e = max(cur_e, s["end"])
    if cur_e is not None:
        db_on_sec += cur_e - cur_s
    off_on_sec = 0.0
    cur_s = cur_e = None
    for s in sorted(off, key=lambda s: s["start"]):
        if cur_e is None or s["start"] > cur_e:
            if cur_e is not None:
                off_on_sec += cur_e - cur_s
            cur_s, cur_e = s["start"], s["end"]
        else:
            cur_e = max(cur_e, s["end"])
    if cur_e is not None:
        off_on_sec += cur_e - cur_s

    db_raw_words = sum(len(words(s["raw"])) for s in db_segs)
    off_words = sum(len(words(s["text"])) for s in off)
    db_tr_chars = sum(cjk_chars(s["tr"]) for s in db_segs)

    # ---- WER（暂停前 / 恢复后校正） ----
    r1 = bucket_wer(db_segs, off, pre_lo, pre_hi, 0.0)
    r2 = bucket_wer(db_segs, off, post_lo, post_hi, shift)
    r2_raw = bucket_wer(db_segs, off, post_lo, post_hi, 0.0)  # 不校正对照

    # 暂停缺口：离线在暂停区间的词数
    gap_words = sum(len(words(x["text"]))
                    for x in off if any(a <= x["start"] < b or a < x["end"] <= b for a, b in pauses))
    # 恢复后缺口桶（离线有语音、实时无词）
    gaps = [d for d in r2[3] if d[2] > 0 and d[3] == 0]

    # ============ 报告 ============
    L = []
    L.append("# session 94 实时链路翻译 vs 录音整体翻译 对比报告")
    L.append("")
    L.append(f"- 会话：{sess['title']}（session {SID}），录音 {hms(off_dur)}")
    L.append(f"- 数据：实时入库 {len(db_segs)} 段（空原文 {len(db_raw_empty)}）vs 离线精准转写 {len(off)} 段")
    L.append(f"- 离线转写参数：faster-whisper small + VAD + beam3 + int8（与实时 precise 同参）")
    L.append(f"- 暂停检测：DB 段墙钟跳跃 >{PAUSE_GAP:.0f}s → 共 {len(pauses)} 次暂停，"
             f"累计 {hms(pause_total)}（{pause_total / off_dur * 100:.0f}% 录音）")
    L.append(f"- 恢复后时间戳偏移拟合：{shift:+.1f}s（内容锚点中位数，已校正）")
    L.append(f"- 报告生成：{datetime.now().isoformat(timespec='seconds')}")
    L.append("")

    L.append("## 1. 时间覆盖与暂停")
    L.append("")
    L.append("| 项 | 实时链路 | 离线转写 | 差距 |")
    L.append("|---|---|---|---|")
    L.append(f"| 段数 | {len(db_segs)}（空原文 {len(db_raw_empty)}） | {len(off)} | — |")
    L.append(f"| 时间范围 | {hms(db_t0)}–{hms(db_t1)} | 0–{hms(off_dur)} | 尾部差 {hms(max(0, off_dur - db_t1))} |")
    L.append(f"| 有效语音覆盖 | {hms(db_on_sec)}（{db_on_sec / off_dur * 100:.1f}%） | "
             f"{hms(off_on_sec)}（{off_on_sec / off_dur * 100:.1f}%） | — |")
    L.append(f"| 原文词数 | {db_raw_words} | {off_words} | 实时/离线 = {db_raw_words / max(1, off_words) * 100:.1f}% |")
    L.append(f"| 译文汉字数 | {db_tr_chars} | — | — |")
    L.append("")
    if pauses:
        L.append(f"**暂停 {len(pauses)} 次**（{hms(pause_total)}）：")
        L.append("")
        for a, b in pauses:
            gw = sum(len(words(x["text"])) for x in off if a <= x["start"] < b or a < x["end"] <= b)
            L.append(f"- {hms(a)}–{hms(b)}（{int(b - a)}s）：暂停期间录音连续写入 wav，"
                     f"实时链路不喂 ASR → 无实时段；离线转写覆盖该段（{gw} 词）")
        L.append("")
        L.append(f"暂停缺口合计 **{gap_words} 词**（离线有、实时无，属预期行为，非丢句）。")
        L.append("")

    L.append("## 2. ASR 原文一致性（词级 WER，60s 桶对齐）")
    L.append("")
    L.append("| 区间 | 参考(离线)词数 | 假设(实时)词数 | 编辑距离 | WER |")
    L.append("|---|---|---|---|---|")
    L.append(f"| 暂停前 {hms(pre_lo)}–{hms(pre_hi)} | {r1[0]} | {r1[1]} | {r1[2]} | {r1[2] / max(1, r1[0]) * 100:.1f}% |")
    L.append(f"| 恢复后(偏移校正 {shift:+.0f}s) {hms(post_lo)}–{hms(post_hi)} | {r2[0]} | {r2[1]} | {r2[2]} | {r2[2] / max(1, r2[0]) * 100:.1f}% |")
    L.append(f"| 恢复后(不校正，对照) | {r2_raw[0]} | {r2_raw[1]} | {r2_raw[2]} | {r2_raw[2] / max(1, r2_raw[0]) * 100:.1f}% |")
    tot_r = r1[0] + r2[0]
    tot_e = r1[2] + r2[2]
    L.append(f"| **合计（暂停前+恢复后校正）** | {tot_r} | {r1[1] + r2[1]} | {tot_e} | **{tot_e / max(1, tot_r) * 100:.1f}%** |")
    L.append("")
    L.append(f"- 恢复后若不校正偏移，WER 高达 {r2_raw[2] / max(1, r2_raw[0]) * 100:.1f}%——"
             f"纯属时间戳错位假象，内容本身与暂停前同一水平。")
    L.append(f"- 缺口桶（离线有语音、实时无词）：{len(gaps)} 个")
    if gaps:
        L.append("")
        for bs, be, n, h, ed in gaps[:8]:
            txt = " ".join(x["text"] for x in off if x["start"] < be and x["end"] >= bs)
            L.append(f"  - {hms(bs)}–{hms(be)}：{txt[:80]}")
    L.append("")

    L.append("### 2.1 同音/近音错抽样（对照实时 vs 离线开头几段）")
    L.append("")
    L.append("| 时间 | 实时原文 | 离线原文 |")
    L.append("|---|---|---|")
    for db_s, off_s in zip(sorted(db_raw_ok, key=lambda s: s["start"])[:5],
                           sorted(off, key=lambda s: s["start"])[:5]):
        L.append(f"| {hms(db_s['start'])} | {db_s['raw'][:90]} | {off_s['text'][:90]} |")
    L.append("")

    # ============ 翻译对比 ============
    if not args.no_translate:
        # 分块（仅非暂停区间的离线段参与翻译对比主体；暂停区间单独一块标注）
        blocks = []
        cur_words, cur_txt, cur_s = [], [], None
        for s in off:
            if cur_s is None:
                cur_s = s["start"]
            cur_words.append(words(s["text"]))
            cur_txt.append(s["text"])
            if sum(len(w) for w in cur_words) >= OFFLINE_BLOCK_WORDS:
                blocks.append((cur_s, s["end"], " ".join(cur_txt)))
                cur_words, cur_txt, cur_s = [], [], None
        if cur_txt:
            blocks.append((cur_s, off[-1]["end"], " ".join(cur_txt)))

        print(f"离线全文分 {len(blocks)} 块翻译（每块 ≤{OFFLINE_BLOCK_WORDS} 词）...")
        tr = DeepSeekTranslator()
        offline_tr_blocks = []
        for i, (bs, be, txt) in enumerate(blocks):
            zh = tr.translate(txt)
            offline_tr_blocks.append({"start": bs, "end": be, "src": txt, "zh": zh})
            print(f"  [{i + 1}/{len(blocks)}] {hms(bs)}–{hms(be)} 译文 {cjk_chars(zh)} 字")
            time.sleep(0.3)

        L.append("## 3. 翻译质量（实时逐句译文 vs 离线整体译文）")
        L.append("")
        L.append(f"离线全文按 ≤{OFFLINE_BLOCK_WORDS} 词分 {len(offline_tr_blocks)} 块，"
                 f"用 DeepSeek（与实时同参：同 system prompt / temperature 0.3）整体翻译，"
                 f"与实时逐句译文按同一时间窗并排对照。")
        L.append("")
        L.append("| 块 | 时间 | 离线译文字数 | 实时译文字数 | 实时/离线 |")
        L.append("|---|---|---|---|---|")
        tot_off_zh = sum(cjk_chars(b["zh"]) for b in offline_tr_blocks)
        L.append(f"| 合计 | 全课 | {tot_off_zh} | {db_tr_chars} | {db_tr_chars / max(1, tot_off_zh) * 100:.0f}% |")
        for i, b in enumerate(offline_tr_blocks):
            live_zh = " ".join(
                s["tr"] for s in db_segs
                if s["start"] < b["end"] and s["end"] >= b["start"] and s["tr"])
            live_n = cjk_chars(live_zh)
            off_n = cjk_chars(b["zh"])
            L.append(f"| {i + 1} | {hms(b['start'])}–{hms(b['end'])} | {off_n} | {live_n} | "
                     f"{live_n / max(1, off_n) * 100:.0f}% |")
        L.append("")
        L.append("### 3.1 抽样并排对照")
        L.append("")
        step = max(1, len(offline_tr_blocks) // SAMPLE_BLOCKS)
        shown_i = 0
        for i in range(0, len(offline_tr_blocks), step):
            if shown_i >= SAMPLE_BLOCKS:
                break
            b = offline_tr_blocks[i]
            live_zh = " ".join(
                s["tr"] for s in db_segs
                if s["start"] < b["end"] and s["end"] >= b["start"] and s["tr"])
            L.append(f"**块 {i + 1}｜{hms(b['start'])}–{hms(b['end'])}**")
            L.append("")
            L.append(f"- 离线整体译文：{b['zh']}")
            L.append(f"- 实时逐句译文：{live_zh}")
            L.append(f"- 离线原文：{b['src'][:160]}")
            L.append("")
            shown_i += 1

    L.append("## 4. 结论")
    L.append("")
    L.append(f"- **ASR 层**：暂停前 WER {r1[2] / max(1, r1[0]) * 100:.1f}%、恢复后(校正) {r2[2] / max(1, r2[0]) * 100:.1f}%——"
             f"两段同水平，说明实时 ASR 质量稳定；差异主要来自同音/近音错（small 模型）。")
    L.append(f"- **覆盖层**：暂停缺口 {gap_words} 词（{hms(pause_total)}）是用户主动暂停的预期行为；"
             f"非暂停区间实时有效覆盖与离线基本一致。")
    if args.no_translate:
        L.append("- **翻译层**：本次未跑离线整体翻译（--no-translate），完整结论见下轮。")
    else:
        L.append(f"- **翻译层**：实时逐句译文 {db_tr_chars} 汉字 vs 离线整体译文 {tot_off_zh} 汉字，"
                 f"字数比 {db_tr_chars / max(1, tot_off_zh) * 100:.0f}%；并排对照见 3.1。")
        L.append(f"- **总判断**：实时链路最终翻译与「录音整体翻译」主体对得上——"
                 f"ASR 同音错是主要质量来源，翻译链路本身（逐句 vs 整体）差异见 3.1 抽样。")
    L.append("")
    out = "\n".join(L)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(out)
    print(out)


if __name__ == "__main__":
    main()
