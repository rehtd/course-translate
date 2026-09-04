"""麦克风权限：macOS 弹系统对话框；Windows 打开输入流触发系统授权。

macOS 不额外依赖 AVFoundation 的 pip 包：用已有的 Cocoa/objc 加载系统框架。
Windows 用 PortAudio 试开一次麦；拒绝后 open_settings() 打开 ms-settings。
"""
from __future__ import annotations

import sys
import threading

_MEDIA = "soun"  # AVMediaTypeAudio 的四字符码
_STATUS = {
    0: "not_determined",
    1: "restricted",
    2: "denied",
    3: "authorized",
}
_registered = False


def settings_urls() -> tuple[str, ...]:
    """系统设置 → 麦克风 的 URL（新系统优先）。"""
    if sys.platform == "win32":
        return ("ms-settings:privacy-microphone",)
    return (
        "x-apple.systemsettings:com.apple.settings.PrivacySecurity.extension?Privacy_Microphone",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    )


def _capture_device():
    """加载 AVFoundation 并补上 completionHandler 的 block 签名。"""
    global _registered
    if sys.platform != "darwin":
        return None
    import objc
    from Foundation import NSBundle

    bundle = NSBundle.bundleWithPath_(
        "/System/Library/Frameworks/AVFoundation.framework")
    if bundle is None or not bundle.load():
        return None
    cls = objc.lookUpClass("AVCaptureDevice")
    if cls is None:
        return None
    if not _registered:
        objc.registerMetaDataForSelector(
            b"AVCaptureDevice",
            b"requestAccessForMediaType:completionHandler:",
            {
                "arguments": {
                    3: {
                        "callable": {
                            "retval": {"type": b"v"},
                            "arguments": {
                                0: {"type": b"^v"},
                                1: {"type": objc._C_NSBOOL},
                            },
                        }
                    }
                }
            },
        )
        _registered = True
        try:
            info = NSBundle.mainBundle().infoDictionary()
            if info is not None and "NSMicrophoneUsageDescription" not in info:
                info["NSMicrophoneUsageDescription"] = (
                    "上课录音需要使用麦克风做实时同传。")
        except Exception:  # noqa: BLE001
            pass
    return cls


def status() -> str:
    """authorized / denied / not_determined / restricted / unknown。"""
    try:
        cls = _capture_device()
        if cls is None:
            return "unknown"
        return _STATUS.get(int(cls.authorizationStatusForMediaType_(_MEDIA)), "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def _finish_cb(on_done, ok: bool) -> None:
    try:
        on_done(bool(ok))
    except Exception:  # noqa: BLE001
        pass


def _probe_win_input() -> bool:
    """试开一次输入流：Win10/11 常在此时弹出「允许麦克风」。可能阻塞，须在后台线程调用。"""
    try:
        import sounddevice as sd
        device = None
        try:
            from app import settings
            device = settings.load().get("input_device") or None
        except Exception:  # noqa: BLE001
            pass
        kwargs = dict(samplerate=16000, channels=1, dtype="float32", blocksize=512)
        if device:
            kwargs["device"] = device
        stream = sd.InputStream(**kwargs)
        stream.start()
        stream.stop()
        stream.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _request_win(on_done, parent=None) -> None:
    """后台试开麦克风，避免堵死 Qt 界面（否则「新建一节课」会点不了）。"""
    from PySide6.QtCore import QObject, QTimer, Signal

    class _Bridge(QObject):
        decided = Signal(bool)

    bridge = _Bridge(parent)
    state = {"done": False}

    def _finish(ok: bool):
        if state["done"]:
            return
        state["done"] = True
        try:
            _finish_cb(on_done, ok)
        finally:
            try:
                bridge.deleteLater()
            except RuntimeError:
                pass

    bridge.decided.connect(_finish)
    # 设备/系统弹窗卡住时也不让「新建」一直等
    QTimer.singleShot(12000, lambda: _finish(False))

    def work():
        ok = _probe_win_input()
        try:
            bridge.decided.emit(ok)
        except RuntimeError:
            pass

    threading.Thread(target=work, daemon=True, name="win-mic-request").start()


def request(on_done, parent=None) -> None:
    """弹出系统「允许麦克风」对话框。on_done(granted: bool) 在 Qt 线程调用。"""
    if sys.platform == "win32":
        _request_win(on_done, parent)
        return

    cls = _capture_device()
    if cls is None:
        on_done(False)
        return

    def _finish(ok: bool):
        _finish_cb(on_done, ok)

    try:
        from PySide6.QtCore import QObject, Signal

        class _Bridge(QObject):
            decided = Signal(bool)

        bridge = _Bridge(parent)

        def _slot(ok: bool):
            try:
                _finish(ok)
            finally:
                bridge.deleteLater()

        bridge.decided.connect(_slot)

        def handler(granted):
            bridge.decided.emit(bool(granted))

        cls.requestAccessForMediaType_completionHandler_(_MEDIA, handler)
    except Exception:  # noqa: BLE001
        def handler(granted):
            _finish(granted)

        try:
            cls.requestAccessForMediaType_completionHandler_(_MEDIA, handler)
        except Exception:  # noqa: BLE001
            _finish(False)


def open_settings() -> bool:
    """打开系统设置里的麦克风开关页，避免用户自己翻。"""
    if sys.platform == "win32":
        import os
        try:
            os.startfile("ms-settings:privacy-microphone")
            return True
        except OSError:
            return False
    if sys.platform != "darwin":
        return False
    import subprocess
    for url in settings_urls():
        try:
            r = subprocess.run(["open", url], check=False, capture_output=True)
            if r.returncode == 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def looks_like_denied(exc: BaseException) -> bool:
    msg = str(exc).lower()
    keys = (
        "-9986", "device unavailable", "invalid number of channels",
        "error opening input", "not authorized", "permission",
        "access denied", "microphone", "paerror", "unanticipated host error",
        "invalid device", "host error",
    )
    return any(k in msg for k in keys)
