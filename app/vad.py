"""VAD 分块：把连续音频流切成「一句/一段」，供 ASR 使用。

优先使用 silero-vad（ONNX/torch），失败时回退到简单能量阈值。
注意：silero 6.x 要求每帧恰好 512 样本（16kHz），内部做缓冲切分。
产出回调 on_chunk(audio: np.ndarray, t_start: float, t_end: float)，
时间基于 time.time() 墙钟（用于落库时间戳），单位秒。
"""
import time

import numpy as np

try:
    from silero_vad import load_silero_vad, VADIterator
    _HAS_SILERO = True
except Exception:  # noqa: BLE001
    _HAS_SILERO = False

SILERO_FRAME = 512  # 16kHz 下 silero 固定帧长


class SpeechChunker:
    def __init__(self, sr: int = 16000, threshold: float = 0.5,
                 silence_tail: float = 0.6, max_chunk: float = 10.0,
                 on_chunk=None):
        self.sr = sr
        self.max_chunk = int(max_chunk * sr)
        self.silence_tail = silence_tail
        self.on_chunk = on_chunk or (lambda a, s, e: None)

        self.chunk = np.zeros(0, dtype=np.float32)
        self.buf = np.zeros(0, dtype=np.float32)  # silero 帧缓冲
        self.speech = False
        self.chunk_t0 = None
        self._vad = None

        if _HAS_SILERO:
            try:
                model = load_silero_vad(onnx=True)
            except Exception:  # noqa: BLE001
                try:
                    model = load_silero_vad()
                except Exception:  # noqa: BLE001
                    model = None
            if model is not None:
                try:
                    self._vad = VADIterator(model, threshold=threshold, sampling_rate=sr,
                                            min_silence_duration_ms=int(silence_tail * 1000))
                except Exception:  # noqa: BLE001
                    self._vad = None

        if self._vad is None:
            print("[vad] silero 不可用，回退到能量阈值模式")
            self._energy_th = 0.01
            self._silence_run = 0.0

    def feed(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if len(samples) == 0:
            return
        if self.chunk_t0 is None:
            self.chunk_t0 = time.time()
        self.chunk = np.concatenate([self.chunk, samples])

        if self._vad is not None:
            self.buf = np.concatenate([self.buf, samples])
            while len(self.buf) >= SILERO_FRAME:
                frame = self.buf[:SILERO_FRAME]
                self.buf = self.buf[SILERO_FRAME:]
                try:
                    d = self._vad(frame)
                except Exception:  # noqa: BLE001
                    d = None
                if d:
                    if "start" in d and not self.speech:
                        self.speech = True
                    if "end" in d and self.speech:
                        self._emit()
                        break
        else:
            rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
            if rms > self._energy_th:
                self.speech = True
                self._silence_run = 0.0
            elif self.speech:
                self._silence_run += len(samples) / self.sr
                if self._silence_run >= self.silence_tail:
                    self._emit()

        # 超长强制截断，避免单块过大；同时重置 VAD 状态防失同步
        if self.speech and len(self.chunk) >= self.max_chunk:
            self._emit()
            if self._vad is not None:
                try:
                    self._vad.reset_states()
                except Exception:  # noqa: BLE001
                    pass

    def _emit(self):
        if len(self.chunk) > 0:
            t1 = self.chunk_t0 + len(self.chunk) / self.sr
            self.on_chunk(self.chunk.copy(), self.chunk_t0, t1)
        self.chunk = np.zeros(0, dtype=np.float32)
        self.buf = np.zeros(0, dtype=np.float32)
        self.speech = False
        self.chunk_t0 = None

    def flush(self):
        if len(self.chunk) > 0:
            self._emit()
        if self._vad is not None:
            try:
                self._vad.reset_states()
            except Exception:  # noqa: BLE001
                pass
