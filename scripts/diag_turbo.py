"""v3.7+ 实测：faster-whisper large-v3-turbo 单次短窗推理（M5）。

对比 small/medium 的同款测试：3s 窗 beam1（草稿）+ 5s 窗 beam5（定稿）。
下载模型约 1.6GB（首次自动下载），之后缓存。
"""
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

wf = wave.open(str(ROOT / "data/audio/session_96.wav"), "rb")
sr = wf.getframerate()
audio = np.frombuffer(wf.readframes(sr * 20), dtype=np.int16).astype(np.float32) / 32768.0
wf.close()

from faster_whisper import WhisperModel

t0 = time.time()
m = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
print(f"turbo 加载（含下载）: {time.time()-t0:.1f}s", flush=True)


def ts(seg, beam):
    segs, _ = m.transcribe(seg, beam_size=beam, language="en")
    return " ".join(s.text for s in segs)


for i in range(3):
    seg = audio[int(sr * 5):int(sr * 8)]
    t0 = time.time()
    text = ts(seg, 1)
    print(f"turbo beam1 3s窗 第{i+1}次: {time.time()-t0:.2f}s  {text[:60]!r}", flush=True)

for i in range(2):
    seg = audio[int(sr * 5):int(sr * 10)]
    t0 = time.time()
    text = ts(seg, 5)
    print(f"turbo beam5 5s窗 第{i+1}次: {time.time()-t0:.2f}s  {text[:60]!r}", flush=True)
