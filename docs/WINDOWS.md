# Windows 适配清单

这次仓库里的代码仍按 **macOS** 上课来。Windows 上请开分支 `feat/windows` 再改，做完用下面清单验收。识别、翻译、落库主路径不必重写。

## 必须改

1. **悬浮窗层级** — [`app/overlay.py`](../app/overlay.py) 的 `make_floating` / `_apply_native_level` 依赖 `AppKit` 和 `pyobjc`。Windows 上：
   - 保留 `Qt.WindowStaysOnTopHint | Qt.Tool`
   - `WA_MacAlwaysShowToolWindow` 仅在 Darwin 设置
   - 字幕点击穿透：Windows 给 HWND 加 `WS_EX_TRANSPARENT | WS_EX_LAYERED`（只靠 `WA_TransparentForMouseEvents` 往往不够）
   - 每 3 秒复查 NSWindow level 的定时器只给 macOS

2. **打开笔记** — [`app/ui/main_window.py`](../app/ui/main_window.py) 里 `subprocess.Popen(["open", "obsidian://..."])` 是 macOS 的 `open`。Windows 用 `os.startfile(url)` 或 `QDesktopServices.openUrl`。

3. **字体** — QSS / 字幕里的 `PingFang SC`、`Helvetica Neue`、`Menlo` 在 Windows 上没有。改成候选链，例如 `"PingFang SC", "Microsoft YaHei", "Segoe UI"`；等宽 `"Menlo", "Consolas", "Cascadia Mono"`。

4. **麦克风文案** — 启动失败提示不要写「系统设置 → 隐私与安全性」。改成 Windows：设置 → 隐私和安全性 → 麦克风，允许该 Python/应用。

不要把 `pyobjc` 写进 `requirements.txt`。

## 不要改（除非修跨平台 bug）

- `app/asr.py`、`app/translate.py`、`app/storage.py`、`app/recorder.py` 的切句/落库逻辑
- 录制「上英下中」/ 回看「一句一块」的产品行为

## 运行方式

不要用仓库里的 `.app` / `.command`（那些绑定了某台 Mac 的解释器）。

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

可另加 `run.bat` 调用 `.venv\Scripts\python.exe -u main.py`。

注意：

- 隐私里打开麦克风后，确认 `sounddevice` 用的是课堂那只麦（有时默认成立体声混音）
- Whisper 继续 `device="cpu"` 最稳；CUDA 另说，不要当默认
- 模型第一次下载到 `%USERPROFILE%\.cache`，体积大

## 验收

在一台 Windows 上走通：新建一节 → 录制（双框有定稿）→ 暂停/继续 → 结束 → 点课节回看（上英下中）→ 双击回听 → 计入笔记（若已配 vault）。悬浮字幕置顶、不挡鼠标点 PPT。
