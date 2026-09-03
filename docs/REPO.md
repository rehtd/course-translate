# 仓库规范

远程：<https://github.com/rehtd/course-translate>（私有）。

## 分支

- `main`：可在 macOS 上安装后上课用的源码
- Windows 适配：从 `main` 拉 `feat/windows`，做完再开 Pull Request，不要把半成品直接推 `main`
- 提交说明写清为什么改，一两句即可

## 不要提交

| 路径 | 原因 |
|------|------|
| `.env` | 真实 API Key |
| `data/` | 录音、SQLite、本机 Obsidian 路径、日志 |
| `*.wav` | 课堂原声 |
| `.venv/`、`__pycache__/` | 本机环境 |
| `同传课堂.app/`、`启动同传课堂.command`、`launcher_stub.c` | 写死了某台 Mac 的 Python 路径 |

模板用 [`.env.example`](../.env.example)。每人自己 `cp .env.example .env`。

Whisper / Hugging Face 模型缓存在用户目录（如 `~/.cache`），不要拷进仓库。

## 怎么加文件

不要 `git add .`。先 `git status`，确认没有 `.env`、`data/`、wav，再按路径 add。

误把密钥推进去了：立刻轮换该 Key，不要只靠 `git rm` 当没发生过（历史里还在）。

## 测试

改 UI 或转写路径时，在 macOS 上至少跑：

```bash
export QT_QPA_PLATFORM=offscreen
export DEEPSEEK_API_KEY=sk-test-dummy
python tests/test_mainwindow_smoke.py
python scripts/smoke_v3_dual_pane.py
```
