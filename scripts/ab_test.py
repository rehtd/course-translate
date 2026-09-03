"""A/B 实测 v2：模拟 final 定稿链路 + WER 对比（真实课堂音频）。

真实字幕的「有效内容」= final 定稿序列（beam=5、句子级、去重入库）。
本脚本模拟该链路：每 final_win 秒对最近 win 秒窗口做 beam=5 转写，
同句去重后拼接 → 与离线标准原文对比 WER，量化窗口/VAD/模型对精度的影响。

用法: <venv>/bin/python scripts/ab_test.py [--model small|medium] [--win 5|10] [--vad]
默认跑 small 三档（5s 现状 / 5s+VAD / 10s+VAD 精准模式）。
"""
import argparse
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.recorder import _same_sentence  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WAV = ROOT / "data/audio/session_92.wav"
OFFLINE = ROOT / "data/exports/session_92_offline_small.json"
SR = 16000
FINAL_WIN = 5.0          # 定稿周期：每 5s 定稿一次（真实链路周期/稳定/超时定稿的近似）
SEG_START = 300.0
SEG_END = 480.0


def load_wav_seg(path, t0, t1):
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getsampwidth() == 2
        w.setpos(int(t0 * SR))
        raw = w.readframes(int((t1 - t0) * SR))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def reference_text(off, t0, t1):
    return " ".join(o["text"] for o in off if o["start"] < t1 and o["end"] > t0)


def lev_words(a, b):
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (0 if a[i - 1] == b[j - 1] else 1))
        prev = cur
    return prev[n]


def wer(hyp, ref):
    h, r = hyp.split(), ref.split()
    if not r:
        return 0.0, 0, 0
    d = lev_words(h, r)
    return d / len(r), d, len(r)


def simulate(model, win, vad, off):
    audio = load_wav_seg(WAV, SEG_START, SEG_END)
    final_texts = []
    last = ""
    n_asr = 0
    t0 = time.time()
    # 定稿周期 = 窗口大小（首尾相接，无重叠；对应 recorder 周期定稿 fed-last>=asr_win）
    t = win
    while t <= len(audio) / SR + win:
        # 模拟 feed_loop：窗口内容 = 最近 win 秒（真实 ring 累积）
        seg = audio[int(max(0, t - win) * SR):int(t * SR)]
        segments, _ = model.transcribe(seg, beam_size=5, language="en",
                                       vad_filter=vad)
        text = " ".join(s.text.strip() for s in segments).strip()
        n_asr += 1
        if text and not _same_sentence(text, last):
            final_texts.append(text)
            last = text
        t += win
    dur = time.time() - t0
    hyp = " ".join(final_texts)
    ref = reference_text(off, SEG_START, SEG_END)
    w, d, r = wer(hyp, ref)
    name = getattr(model, "_name", "?")
    print(f"[{name} win={win}s vad={vad}] WER={w*100:.1f}% ({d}/{r}) | "
          f"final {len(final_texts)} 条 | ASR {n_asr} 次 | 模拟 {dur:.0f}s | RTF~{dur/(SEG_END-SEG_START):.2f}")
    return {"model": name, "win": win, "vad": vad, "wer": round(w * 100, 1),
            "d": d, "r": r, "n_final": len(final_texts), "hyp": hyp, "ref": ref}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="small")
    ap.add_argument("--win", type=float)
    ap.add_argument("--vad", action="store_true")
    args = ap.parse_args()

    off = json.loads(OFFLINE.read_text(encoding="utf-8"))
    if args.win is not None:
        configs = [(args.win, args.vad)]
    else:
        configs = [(5.0, False), (5.0, True), (10.0, True)]

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    model._name = args.model
    results = []
    for w, v in configs:
        results.append(simulate(model, w, v, off))
        print()

    (ROOT / "data/exports/ab_test_result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[saved data/exports/ab_test_result.json]")


if __name__ == "__main__":
    main()
