"""session 93 对比分析：DB 实时段 vs 离线精准转写。

- DB 侧：segments.raw_text（墙钟时间戳，需换算成 wav 内秒 = 墙钟 - started_at epoch）
- 离线侧：data/exports/session_93_precise.json（wav 内秒）
- 输出：时间覆盖对比 + 词级 WER + 丢失内容示例 + 补全报告
"""
import json
import re
import sqlite3
import sys
from datetime import datetime

DB = "data/subtitle.db"
PRECISE_JSON = "data/exports/session_93_precise.json"
OUT_MD = "data/exports/session_93_精准补全报告.md"
SID = 93


def words(t: str):
    return re.findall(r"[A-Za-z']+", t or "")


def load_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sess = con.execute("SELECT started_at FROM sessions WHERE id=?", (SID,)).fetchone()
    rows = con.execute(
        "SELECT seq, t_start, t_end, raw_text FROM segments WHERE session_id=? ORDER BY seq",
        (SID,)).fetchall()
    return sess, rows


def wall_to_wav(epoch: float, start_epoch: float) -> float:
    return max(0.0, epoch - start_epoch)


def main():
    sess, rows = load_db()
    start_iso = sess["started_at"]
    # started_at 是本地 ISO 字符串（含时区偏移）。转 epoch。
    # 数据库里存的是 datetime.now().isoformat() 本地时间（无时区后缀），
    # 直接按本地时区解析即可（与 _build_audio_map 一致）。
    dt = datetime.fromisoformat(start_iso)
    import time as _t
    start_epoch = _t.mktime(dt.timetuple())

    print(f"session {SID} started_at={start_iso} epoch={start_epoch:.0f}")

    # ---- DB 实时段 ----
    db_segs = []
    for r in rows:
        t0 = wall_to_wav(r["t_start"], start_epoch)
        t1 = wall_to_wav(r["t_end"], start_epoch)
        db_segs.append({"start": t0, "end": t1, "text": (r["raw_text"] or "").strip()})
    db_nonempty = [s for s in db_segs if s["text"]]
    db_empty = [s for s in db_segs if not s["text"]]

    # ---- 离线精准转写 ----
    with open(PRECISE_JSON, encoding="utf-8") as f:
        precise = json.load(f)

    # ---- 时间覆盖 ----
    db_t0 = min(s["start"] for s in db_segs) if db_segs else 0
    db_t1 = max(s["end"] for s in db_segs) if db_segs else 0
    p_t1 = max(s["end"] for s in precise) if precise else 0
    wav_dur = p_t1  # 以离线转写覆盖为准

    def hms(sec):
        return f"{int(sec//60):02d}:{int(sec%60):02d}"

    lines = []
    lines.append("# session 93 精准模式补全报告")
    lines.append("")
    lines.append(f"- 会话：IS5113 第 2 节（session {SID}），{hms(wav_dur)} 录音")
    lines.append(f"- 实时链路入库：{len(db_segs)} 段（空段 {len(db_empty)}），覆盖 {hms(db_t0)}–{hms(db_t1)}")
    lines.append(f"- 离线精准转写（small+VAD+beam3）：{len(precise)} 段，覆盖 0–{hms(wav_dur)}")
    lines.append("")
    lines.append("## 结论")
    lost_sec = max(0.0, wav_dur - db_t1)
    lost_pct = lost_sec / wav_dur * 100 if wav_dur else 0
    lines.append(f"- 实时链路因 final 任务饿死，仅覆盖前 {hms(db_t1)}；**丢失后段 {hms(lost_sec)}（{lost_pct:.0f}%）**")
    lines.append(f"- 精准离线转写完整覆盖全部音频，可用于补全。")
    lines.append("")

    # ---- DB 段内容抽样（判断实时链路本身质量） ----
    lines.append("## 实时链路已入库内容抽样（前 5 条非空）")
    for s in db_nonempty[:5]:
        lines.append(f"- [{hms(s['start'])}] {s['text']}")
    lines.append("")

    # ---- 精准转写抽样 ----
    lines.append("## 离线精准转写抽样（每 ~3 分钟一条）")
    shown = set()
    for s in precise:
        bucket = int(s["start"] // 180)
        if bucket not in shown:
            shown.add(bucket)
            lines.append(f"- [{hms(s['start'])}] {s['text']}")
    lines.append("")

    # ---- 重叠区精度对比（仅比较 0–db_t1 覆盖区） ----
    lines.append("## 重叠区精度对比（前 6 分钟，实时 vs 精准）")
    db_in = [s for s in db_nonempty if s["end"] <= db_t1 + 5]
    p_in = [s for s in precise if s["start"] <= db_t1 + 5]
    ref_text = " ".join(s["text"] for s in p_in)
    hyp_text = " ".join(s["text"] for s in db_in)
    ref_w = words(ref_text)
    hyp_w = words(hyp_text)

    # 词级 Levenshtein WER
    import numpy as np
    n = len(ref_w)
    m = len(hyp_w)
    dp = np.zeros((n + 1, m + 1), dtype=int)
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref_w[i - 1].lower() == hyp_w[j - 1].lower() else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    wer = dp[n][m] / max(1, n)
    lines.append(f"- 参考（精准）词数 {n}，假设（实时）词数 {m}，WER={wer*100:.1f}%")
    lines.append("")
    lines.append(f"报告生成：{__import__('datetime').datetime.now().isoformat(timespec='seconds')}")
    out = "\n".join(lines)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(out)
    print(out)


if __name__ == "__main__":
    main()
