"""音频源：麦克风实时采集或 wav 文件模拟（测试），输出 float32 块到队列。
可同时把采集到的音频写入 wav 文件（wav_out），供回放使用。
"""
import queue
import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf


class AudioSource:
    def __init__(self, sample_rate: int = 16000, block_sec: float = 0.1,
                 wav_file: str | None = None, fast: bool = False,
                 wav_out: str | None = None):
        self.sr = sample_rate
        self.block = int(sample_rate * block_sec)
        self.wav_file = wav_file
        self.fast = fast
        self.q: "queue.Queue[np.ndarray | None]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wav = None
        if wav_out and wav_file is None:  # 仅麦克风模式支持录制到文件
            import wave
            self._wav = wave.open(str(wav_out), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(sample_rate)

    def start(self):
        if self.wav_file:
            self._thread = threading.Thread(target=self._run_file, daemon=True)
            self._thread.start()
            return
        # 麦克风：同步打开流——权限/设备错误会在此处抛出，便于上层给出提示
        self._stream = sd.InputStream(samplerate=self.sr, channels=1, dtype="float32",
                                      blocksize=self.block, callback=self._cb)
        self._stream.start()
        self._thread = threading.Thread(target=self._run_mic, daemon=True)
        self._thread.start()

    def _cb(self, indata, frames, t, status):
        self._push(indata[:, 0].copy())

    def _push(self, block: np.ndarray):
        if self._wav is not None:
            self._wav.writeframes((block * 32767).astype(np.int16).tobytes())
        self.q.put(block)

    def _run_file(self):
        # soundfile 不允许对已有文件直接传 samplerate，先按原生采样率读取再插值重采样
        info = sf.info(self.wav_file)
        data, _ = sf.read(self.wav_file, dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = self._resample(data, info.samplerate, self.sr)
        for i in range(0, len(data) - self.block + 1, self.block):
            if self._stop.is_set():
                break
            self._push(data[i:i + self.block])
            if not self.fast:
                time.sleep(self.block / self.sr * 0.8)  # 按实时节奏模拟
        self.q.put(None)

    @staticmethod
    def _resample(data: np.ndarray, src: int, dst: int) -> np.ndarray:
        if src == dst or len(data) == 0:
            return data
        n = int(len(data) * dst / src)
        x_old = np.linspace(0.0, 1.0, len(data), endpoint=False)
        x_new = np.linspace(0.0, 1.0, n, endpoint=False)
        return np.interp(x_new, x_old, data).astype(np.float32)

    def _run_mic(self):
        try:
            while not self._stop.is_set():
                time.sleep(0.05)
        finally:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.q.put(None)

    def read(self) -> np.ndarray | None:
        return self.q.get()

    def stop(self):
        self._stop.set()
        if self._wav is not None:
            self._wav.close()
            self._wav = None
