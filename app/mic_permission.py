"""macOS 麦克风权限：由系统弹窗请求；拒绝后再打开设置页。

不额外依赖 AVFoundation 的 pip 包：用已有的 Cocoa/objc 加载系统框架。
Windows / 测不到权限时返回 unknown，开录走原来的设备错误提示。
"""
from __future__ import annotations

import sys

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


def request(on_done, parent=None) -> None:
    """弹出系统「允许麦克风」对话框。on_done(granted: bool) 在 Qt 线程调用。"""
    cls = _capture_device()
    if cls is None:
        on_done(False)
        return

    def _finish(ok: bool):
        try:
            on_done(bool(ok))
        except Exception:  # noqa: BLE001
            pass

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
        # 没有 Qt 时直接在当前线程回调（测试 / 脚本）
        def handler(granted):
            _finish(granted)

        try:
            cls.requestAccessForMediaType_completionHandler_(_MEDIA, handler)
        except Exception:  # noqa: BLE001
            _finish(False)


def open_settings() -> bool:
    """打开系统设置里的麦克风开关页，避免用户自己翻。"""
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
        "access denied", "microphone",
    )
    return any(k in msg for k in keys)
