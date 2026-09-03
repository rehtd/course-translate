"""ASR 转写：faster-whisper 本地推理。"""
import numpy as np
from faster_whisper import WhisperModel


class Transcriber:
    def __init__(self, model_size: str = "small", beam: int = 5, language: str = "en",
                 vad: bool = False):
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.beam = beam
        self.language = language
        self.vad = vad

    def transcribe(self, audio: np.ndarray, beam: int | None = None,
                   vad: bool | None = None, initial_prompt: str | None = None) -> str:
        """输入 16kHz float32 一维数组，返回识别文本（可能为空）。

        beam 可覆盖默认值：字幕草稿传 beam=1（greedy，快 2-3 倍），
        定稿保持 beam=5（更准）。vad 覆盖 self.vad：定稿开 Silero VAD
        滤掉翻页/咳嗽/空调等非语音段；字幕草稿不开，少一次预处理。

        condition_on_previous_text=False：每个调用是独立滑窗/句段，
        上一窗文本不当下一窗 prompt，避免滑动窗幻觉（环境音脑补）。
        without_timestamps=True：不解码时间戳，字幕草稿明显更快。
        initial_prompt：课程术语英文名，帮 Whisper 拼对人名/课名。
        """
        kwargs = {}
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        segments, _ = self.model.transcribe(
            audio,
            beam_size=beam or self.beam,
            language=self.language,
            vad_filter=self.vad if vad is None else vad,
            condition_on_previous_text=False,
            without_timestamps=True,
            **kwargs,
        )
        return " ".join(s.text.strip() for s in segments).strip()
