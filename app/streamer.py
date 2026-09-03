"""流式滑动窗口引擎：partial 高频更新 + 标点/稳定/超时定稿。

- feed(block, audio_t)：追加音频到环形缓冲，按 partial_win 节流触发 partial 识别
- 定稿（finalize）由 main 侧根据 partial 文本规则触发，避免引擎耦合句子边界判断
"""
import numpy as np


class StreamingEngine:
    def __init__(self, sr: int = 16000, partial_win: float = 1.2,
                 asr_win: float = 5.0, partial_asr_win: float | None = None,
                 ring_sec: float = 9.0,
                 on_partial=None, on_final=None):
        """流式滑动窗口引擎。

        partial_asr_win：字幕草稿窗口（短窗双轨）。短窗（如 3s）只服务
        悬浮字幕，出字快；定稿用 from_t 切「上一句切点 → 现在」整段精修，
        写入右侧框（可慢、必须准）。None 时回退为 asr_win（兼容旧行为）。
        """
        self.sr = sr
        self.partial_win = partial_win
        self.asr_win = asr_win
        self.partial_asr_win = partial_asr_win or asr_win
        self.max_ring = int(ring_sec * sr)
        self.on_partial = on_partial or (lambda audio, t0, t1: None)
        self.on_final = on_final or (lambda audio, t0, t1: None)

        self.ring = np.zeros(0, dtype=np.float32)
        self.last_partial_t = -1e9
        self.reset()

    def reset(self):
        """暂停/恢复时清空缓冲与状态。"""
        self.ring = np.zeros(0, dtype=np.float32)
        self.last_partial_t = -1e9

    def feed(self, block, audio_t: float):
        block = np.asarray(block, dtype=np.float32)
        self.ring = np.concatenate([self.ring, block])
        if len(self.ring) > self.max_ring:
            self.ring = self.ring[-self.max_ring:]

        # partial 节流：每个 partial_win 至少触发一次
        if audio_t - self.last_partial_t >= self.partial_win:
            self.last_partial_t = audio_t
            n = int(self.partial_asr_win * self.sr)
            seg = self.ring[-n:]
            t0 = audio_t - len(seg) / self.sr
            self.on_partial(seg.copy(), t0, audio_t)

    def ring_rms(self) -> float:
        """最近缓冲的均方根能量，用于判断是否有实际语音。"""
        if len(self.ring) == 0:
            return 0.0
        return float(np.sqrt(np.mean(self.ring ** 2)))

    def finalize(self, audio_t: float, from_t: float | None = None):
        """定稿：把音频交给精修识别（写入框内，不走字幕）。

        from_t：上一句切点的音频时刻。传入则切 [from_t, audio_t] 整段
        （受 ring 长度限制），用于等句子说完后再精修，避免固定尾窗丢掉句首。
        None 时回退为最近 asr_win 秒（兼容终端模式）。
        """
        if from_t is None:
            n = int(self.asr_win * self.sr)
        else:
            n = int(max(0.0, audio_t - from_t) * self.sr)
        n = min(n, len(self.ring))
        if n == 0:
            return
        seg = self.ring[-n:]
        t0 = audio_t - len(seg) / self.sr
        self.on_final(seg.copy(), t0, audio_t)
