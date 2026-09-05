# Windows 要注意什么（适配逻辑）

仓库里的 **main 仍是 macOS 上课版**。Windows 上请用 `feat/windows`（本分支已按下列四处改完系统壳）。业务层（识别 / 翻译 / SQLite）不要重写。

识别 / 翻译 / SQLite / 录制上英下中 / 回看一句一块，都不要重写。

## 已经能跑、不用动的

- 主窗口 PySide6、`pathlib`、`.env`、`data/` 落盘
- `sounddevice` + `faster-whisper`（继续 CPU `int8`）
- 笔记写入 Obsidian vault（路径用 Windows 盘符即可）

同学机：Python **3.11+ 64 位**。不要用仓库里的 `同传课堂.app`、`启动同传课堂.command`（写死了某台 Mac 的解释器）。

## 必须改的四处（适配逻辑）

### 1. 悬浮字幕：置顶 + 点击穿透

文件：[`app/overlay.py`](../app/overlay.py)

Mac 用 `AppKit` + `pyobjc` 把窗口抬到 `NSFloatingWindowLevel`，否则切到 PPT 后字幕会沉下去。Windows 没有这套 API，直接调会失败（现在失败只是 print，字幕可能被挡住或点不穿）。

按平台分支，不要删掉 Mac 路径：

| 能力 | macOS（保持） | Windows（新增） |
|------|----------------|-----------------|
| 置顶 | `WindowStaysOnTopHint` + `setLevel_(NSFloatingWindowLevel)` | `WindowStaysOnTopHint` 通常够；必要时 `HWND_TOPMOST` |
| 切应用仍可见 | `WA_MacAlwaysShowToolWindow` + 每 3s 复查 level | **不要**设 `WA_MacAlwaysShowToolWindow`；不要跑 3s 的 NSWindow 定时器 |
| 字幕点穿 | `WA_TransparentForMouseEvents` + Cocoa 行为 | Qt 这个 flag 在 Windows 上经常不够。用 `ctypes` 给 HWND 加 `WS_EX_LAYERED \| WS_EX_TRANSPARENT` |
| 控制条 | 必须能点（暂停/结束） | 控制条 **不要** 加 `WS_EX_TRANSPARENT`，只给 `SubtitleBar` 点穿 |

建议形状：

```python
import sys

def make_floating(widget):
    if sys.platform == "darwin":
        widget.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        _apply_native_level(widget)          # 现有 AppKit
        # 现有 3s 定时器
        return
    if sys.platform == "win32":
        _apply_win_topmost_and_clickthrough(widget)
```

`_apply_native_level` 里的 `from AppKit import ...` 必须留在 Darwin 分支内，Windows 机器没有 pyobjc。

**不要**把 `pyobjc` 写进 `requirements.txt`。

切前台卡死：Mac 上曾经因为激活时碰 `winId()/setLevel` 抢主线程。Windows 改 HWND 也要在窗口 `show()` 之后、最好不要在 `ApplicationActive` 处理函数里同步乱设。字幕点击穿透、控制条可点，两条都要测。

### 2. 打开 Obsidian 笔记

文件：[`app/ui/main_window.py`](../app/ui/main_window.py)（计入笔记成功后）

现在是：

```python
subprocess.Popen(["open", f"obsidian://open?path={quote(str(result.lecture_path))}"])
```

`open` 是 macOS 命令，Windows 会直接失败。

```python
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

url = f"obsidian://open?path={quote(str(result.lecture_path))}"
if sys.platform == "win32":
    os.startfile(url)          # 或 QDesktopServices.openUrl(QUrl(url))
else:
    subprocess.Popen(["open", url])
```

路径里的反斜杠、空格用 `quote` 即可。不要假设 `C:\` 能塞进 Mac 那套 `open`。

### 3. 字体

Windows 没有 `PingFang SC` / `Helvetica Neue` / `Menlo`，会回退成缺字或很难看。

改成**候选链**（Qt 用第一个存在的），Mac 仍把苹方放前面：

- 界面：`"PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif`
- 等宽英文框：`"Menlo", "Consolas", "Cascadia Mono", monospace`
- 悬浮英文字幕 [`SubtitleBar`](../app/overlay.py)：不要只写 `QFont("Helvetica Neue", 28)`，同样加 YaHei / Segoe UI

位置：

- [`app/ui/main_window.py`](../app/ui/main_window.py) 全局 `_APP_QSS` 的 `font-family`
- 录制双框 `_make_box` 的 stylesheet
- [`app/overlay.py`](../app/overlay.py) `self.en.setFont(...)`、控制条 `PingFang SC`

### 4. 麦克风：权限文案 + 选对设备

[`on_record` / `on_continue`](../app/ui/main_window.py) 失败提示现在写的是「系统设置 → 隐私与安全性 → 麦克风 → 允许同传课堂」。Windows 同学按这个找不到。

按平台换文案：

- Windows：设置 → 隐私和安全性 → 麦克风 → 允许桌面应用 / 允许 `python.exe`（或你的启动器）
- 另外检查：没有 Teams/Zoom **独占**麦；Win11 有时默认设备是「立体声混音」而不是课堂麦，`sounddevice` 会录到系统声音或全是静音

`sounddevice` 用 PortAudio/WASAPI，一般不用改 [`app/audio.py`](../app/audio.py)。若课堂麦不是默认设备，再在设置里加输入设备下拉（这是 Windows 上最常见的坑，比代码崩更常见）。

## 运行与环境（上课前）

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
python main.py
```

可双击仓库根目录的 `启动同传课堂.vbs`（无黑框）或 `启动同传课堂.bat`。第一次成功启动会在桌面生成「同传课堂」快捷方式。每人自己填 `.env`，不要拷贝别人的 Key。密钥不要发到聊天里：放到仓库 `keys-inbox/`（Git 忽略）并标明哪家、哪一项，再让 Agent 只改 `.env` 对应行。各家要填什么见 [USAGE.md](USAGE.md) 第 3 节。

注意：

- **CPU Whisper**：保持 `device="cpu"`。有 NVIDIA 再考虑 CUDA，要单独装匹配的 `ctranslate2`，不要当默认。
- **第一次启动慢**：模型下到 `%USERPROFILE%\.cache`（Hugging Face），体积大，提前下或连校园网。
- **回听无声**：PySide6 的 `QMediaPlayer` 依赖自带 FFmpeg 插件；若双击句子没声音，检查 `PySide6` 是否装全、杀毒有没有拦 DLL。
- **高分屏**：Qt6 默认开 DPI 缩放，先不用改；字幕位置若偏，再调 `SubtitleBar` 的 `margin_bottom` / 屏幕几何。
- **路径**：继续用 `pathlib`，不要拼 `C:\` 字符串。Obsidian vault 在设置里选目录即可。

## 明确不要改

- [`app/asr.py`](../app/asr.py)、[`app/translate.py`](../app/translate.py)、[`app/storage.py`](../app/storage.py)、[`app/recorder.py`](../app/recorder.py) 的切句和落库
- 录制双框 / 回看对照的产品行为
- 把 Mac 启动器路径改成你的 Windows 用户名再提交（那些文件 git 已忽略）

## 建议改代码的顺序

1. overlay 平台分支 + 字体候选链 + `open`/`startfile` + 麦克风文案（不改这四样，课上不可用）
2. `run.bat`，本 README 不代替本文
3. 真机走验收（见下）
4. 需要发给不会装 Python 的人，再考虑 PyInstaller **目录版**（不要 `--onefile`，Whisper 太大）

## 验收

在 Windows 上走通一遍：

1. 选课 → 新建一节 → 主区出现上英下中大框
2. 对着麦说话，悬浮英文跟读，且点 PPT 不被字幕挡住
3. 右下角控制条能暂停 / 继续 / 结束
4. 结束后点课节：一句一块上英下中，双击能回听
5. 计入笔记（配好 vault）能打开或至少不报 `open` 找不到命令

切到全屏 PPT / 切回桌面，字幕仍应在最前（控制条可点）。
