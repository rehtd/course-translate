"""麦克风权限：状态枚举、设置 URL、拒绝错误判断（无系统弹窗）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mic_permission import (  # noqa: E402
    looks_like_denied, settings_urls, status,
)


def test_settings_urls_point_at_microphone_pane():
    urls = settings_urls()
    assert urls
    assert all("Microphone" in u for u in urls)
    print("PASS test_settings_urls_point_at_microphone_pane")


def test_status_is_known_token():
    st = status()
    assert st in {
        "authorized", "denied", "not_determined", "restricted", "unknown",
    }
    if sys.platform != "darwin":
        assert st == "unknown"
    print("PASS test_status_is_known_token")


def test_looks_like_denied():
    assert looks_like_denied(RuntimeError("PortAudioError: Error opening InputStream"))
    assert looks_like_denied(OSError(-9986, "Device unavailable"))
    assert not looks_like_denied(RuntimeError("translation timeout"))
    print("PASS test_looks_like_denied")


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
