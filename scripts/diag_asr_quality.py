"""ASR 质量诊断：切片对比 small vs medium 离线识别（beam5+VAD，最佳参数）。

用法: python scripts/diag_asr_quality.py <wav> [--sec 300]
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--sec", type=int, default=300)
    args = ap.parse_args()

    wf = wave.open(args.wav, "rb")
    sr = wf.getframerate()
    n = sr * args.sec
    frames = wf.readframes(min(n, wf.getnframes()))
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    total = wf.getnframes() / sr
    wf.close()
    print(f"[wav] {args.wav} 总长 {total:.0f}s，取前 {len(audio)/sr:.0f}s")

    for model_size in ("small", "medium"):
        from faster_whisper import WhisperModel
        t0 = time.time()
        m = WhisperModel(model_size, device="cpu", compute_type="int8")
        print(f"\n===== {model_size} 加载 {time.time()-t0:.1f}s，识别中… =====")
        t0 = time.time()
        segs, _info = m.transcribe(audio, beam_size=5, language="en", vad_filter=True)
        lines = [f"[{s.start:6.1f}-{s.end:6.1f}] {s.text.strip()}" for s in segs if s.text.strip()]
        print(f"耗时 {time.time()-t0:.1f}s（RTF={ (time.time()-t0)/(len(audio)/sr):.2f}），{len(lines)} 句\n")
        for ln in lines[:40]:
            print(ln)


if __name__ == "__main__":
    main()
