"""课后录音文件：按 stem 解析 wav/m4a，以及把 WAV 压成 AAC（m4a）。

课上仍只写未压缩 WAV。压缩在结束后做，回听走 QMediaPlayer，m4a 即可。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

AUDIO_EXTS = (".wav", ".m4a", ".mp3", ".opus", ".caf")
AAC_BITRATE = 48_000  # 课堂人声足够；16 kHz 16-bit PCM 约 256 kbps → 大约缩到 1/5
PROMPT_MIN_BYTES = 8 * 1024 * 1024  # 小于约 4 分钟的试录不弹窗
_AFCONVERT = Path("/usr/bin/afconvert")


def resolve_audio(directory: Path, name: str) -> Path | None:
    """按文件名找录音；没有精确匹配时用同一 stem 的 wav/m4a 等。"""
    directory = Path(directory)
    exact = directory / Path(name).name
    if exact.is_file():
        return exact
    stem = Path(name).stem
    for ext in AUDIO_EXTS:
        p = directory / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f" {n / 1024:.0f} KB".strip()
    if n < 1024 * 1024 * 1024:
        mb = n / (1024 * 1024)
        return f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


def estimate_m4a_bytes(wav_bytes: int) -> int:
    """16-bit/16 kHz 单声道 PCM → 48 kbps AAC 的粗算。"""
    return max(int(wav_bytes * AAC_BITRATE / 256_000), 1024)


def encoder_available() -> bool:
    return bool(encoder_argv(Path("in.wav"), Path("out.m4a")))


def encoder_argv(src: Path, dest: Path) -> list[str] | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return [
            ffmpeg, "-y", "-i", str(src),
            "-c:a", "aac", "-b:a", "48k", "-ac", "1",
            str(dest),
        ]
    if _AFCONVERT.is_file():
        return [
            str(_AFCONVERT), str(src),
            "-o", str(dest),
            "-f", "m4af", "-d", "aac",
            "-b", str(AAC_BITRATE),
        ]
    return None


def session_wavs(audio_dir: Path, sid: int, extra_names: list[str] | None = None) -> list[Path]:
    """本节仍未压缩的 WAV（主录音 + 续录）。"""
    audio_dir = Path(audio_dir)
    names = [f"session_{sid}.wav"]
    for n in extra_names or []:
        names.append(Path(n).name)
    out: list[Path] = []
    seen: set[Path] = set()
    for name in names:
        p = audio_dir / name
        if p.suffix.lower() != ".wav" or not p.is_file():
            continue
        key = p.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def wav_bytes_total(audio_dir: Path, sid: int, extra_names: list[str] | None = None) -> int:
    return sum(p.stat().st_size for p in session_wavs(audio_dir, sid, extra_names))


def compress_wav(src: Path, *, run=subprocess.run) -> Path:
    src = Path(src)
    if src.suffix.lower() != ".wav":
        raise ValueError(f"只能压缩 WAV：{src}")
    if not src.is_file():
        raise FileNotFoundError(str(src))
    dest = src.with_suffix(".m4a")
    cmd = encoder_argv(src, dest)
    if not cmd:
        raise RuntimeError(
            "没有可用的转码工具（macOS 用自带的 afconvert，或把 ffmpeg 加到 PATH）")
    dest.unlink(missing_ok=True)
    r = run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 64:
        dest.unlink(missing_ok=True)
        err = (r.stderr or r.stdout or "转码失败").strip()
        raise RuntimeError(err[:500])
    src.unlink()
    return dest


def compress_session(
    audio_dir: Path,
    sid: int,
    extra_names: list[str] | None = None,
    *,
    on_progress=None,
    run=subprocess.run,
) -> dict:
    wavs = session_wavs(audio_dir, sid, extra_names)
    if not wavs:
        return {"before": 0, "after": 0, "renamed": []}
    before = sum(p.stat().st_size for p in wavs)
    renamed: list[tuple[str, str]] = []
    for wav in wavs:
        if on_progress:
            on_progress(f"正在压缩 {wav.name}…")
        dest = compress_wav(wav, run=run)
        renamed.append((wav.name, dest.name))
    after = 0
    for _old, new in renamed:
        p = Path(audio_dir) / new
        if p.is_file():
            after += p.stat().st_size
    return {"before": before, "after": after, "renamed": renamed}
