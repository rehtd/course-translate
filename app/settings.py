"""应用设置：vault 路径等，存 data/settings.json。"""
import json

from app import config

SETTINGS_FILE = config.DATA_DIR / "settings.json"
DEFAULTS = {
    "vault": "",
    "notes_subdir": "01-章节笔记",
    "concepts_subdir": "02-概念卡片",
    "translate_provider": "deepseek",
    # 识别模式：realtime=实时（5s 窗+beam1/5、无 VAD，延迟低）；precise=精准（10s 窗+beam3、VAD 滤环境音，更准更稳）
    "asr_mode": "realtime",
    # 麦克风：空=系统默认。Windows 常被设成「立体声混音」，可在设置里改成课堂麦
    "input_device": "",
}


def load() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**DEFAULTS, **data}
        except Exception:  # noqa: BLE001
            pass
    return dict(DEFAULTS)


def save(data: dict):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    merged = {**DEFAULTS, **data}
    SETTINGS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                             encoding="utf-8")
