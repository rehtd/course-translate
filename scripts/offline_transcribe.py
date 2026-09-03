"""离线转写完整 wav → 句子级 JSON（标准原文参照）。

用法:
    python scripts/offline_transcribe.py <wav> [--out out.json] [--model small|medium] [--vad] [--beam N]

输出 JSON: [{"start": float, "end": float, "text": str}, ...]（start/end 为 wav 内秒数）
同时打印每句文本与统计。
"""
import argparse
import json
import time

from faster_whisper import WhisperModel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--out", default=None, help="输出 JSON 路径")
    ap.add_argument("--model", default="small", choices=["small", "medium"])
    ap.add_argument("--vad", action="store_true", help="开启 Silero VAD 过滤非语音段")
    ap.add_argument("--beam", type=int, default=5)
    args = ap.parse_args()

    t0 = time.time()
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    print(f"[model {args.model} loaded in {time.time()-t0:.1f}s]")

    t0 = time.time()
    segments, info = model.transcribe(
        args.wav,
        beam_size=args.beam,
        language="en",
        vad_filter=args.vad,
    )
    segs = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments
        if s.text.strip()
    ]
    dur = time.time() - t0
    audio_sec = info.duration or 0.0
    print(f"[audio {audio_sec:.0f}s | transcribe {dur:.1f}s | RTF={dur/audio_sec:.3f} | {len(segs)} segments]")
    for s in segs:
        print(f"[{s['start']:7.2f}-{s['end']:7.2f}] {s['text']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(segs, f, ensure_ascii=False, indent=1)
        print(f"[saved {args.out}]")


if __name__ == "__main__":
    main()
