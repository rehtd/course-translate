"""录音文件解析与课后压缩。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audio_files import (  # noqa: E402
    compress_session, compress_wav, estimate_m4a_bytes, format_bytes,
    resolve_audio, session_wavs, wav_bytes_total,
)
from app.storage import Store  # noqa: E402


def test_resolve_audio_exact_and_stem():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        wav = d / "session_1.wav"
        wav.write_bytes(b"RIFF")
        assert resolve_audio(d, "session_1.wav") == wav
        wav.unlink()
        m4a = d / "session_1.m4a"
        m4a.write_bytes(b"m4a")
        assert resolve_audio(d, "session_1.wav") == m4a
        assert resolve_audio(d, "missing.wav") is None
        print("PASS test_resolve_audio_exact_and_stem")


def test_format_and_estimate():
    assert format_bytes(500) == "500 B"
    assert "MB" in format_bytes(315 * 1024 * 1024)
    est = estimate_m4a_bytes(256_000)  # 1 second of 256 kbps PCM
    assert 1000 < est < 256_000
    print("PASS test_format_and_estimate")


def _fake_run(cmd, capture_output=True, text=True, timeout=3600):
    dest = Path(next(a for a in cmd if str(a).endswith(".m4a")))
    dest.write_bytes(b"M" * 80)

    class R:
        returncode = 0
        stderr = ""
        stdout = ""
    return R()


def test_compress_wav_deletes_source():
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "session_9.wav"
        wav.write_bytes(b"W" * 1000)
        dest = compress_wav(wav, run=_fake_run)
        assert dest.name == "session_9.m4a"
        assert dest.is_file()
        assert not wav.exists()
        print("PASS test_compress_wav_deletes_source")


def test_compress_session_renames_continue_files():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = 7
        (d / f"session_{sid}.wav").write_bytes(b"A" * 200)
        (d / f"session_{sid}_cont1.wav").write_bytes(b"B" * 200)
        extra = [f"session_{sid}_cont1.wav"]
        assert len(session_wavs(d, sid, extra)) == 2
        assert wav_bytes_total(d, sid, extra) == 400
        result = compress_session(d, sid, extra, run=_fake_run)
        assert result["renamed"] == [
            (f"session_{sid}.wav", f"session_{sid}.m4a"),
            (f"session_{sid}_cont1.wav", f"session_{sid}_cont1.m4a"),
        ]
        assert not (d / f"session_{sid}.wav").exists()
        assert (d / f"session_{sid}.m4a").is_file()
        print("PASS test_compress_session_renames_continue_files")


def test_storage_rename_session_audio_file():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "t.db")
        sid = store.create_session("t")
        store.add_session_audio(sid, 1, "session_1_cont1.wav", 1.0)
        store.rename_session_audio_file(sid, "session_1_cont1.wav", "session_1_cont1.m4a")
        rows = store.list_session_audio(sid)
        assert rows[0][1] == "session_1_cont1.m4a"
        print("PASS test_storage_rename_session_audio_file")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
        except Exception:
            fails += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
