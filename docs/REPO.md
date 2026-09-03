# 仓库规范

远程：<https://github.com/rehtd/course-translate>（私有）。

## 谁能推送（GitHub 权限）

私人仓库、免费账号：**不能**开分支保护 / Ruleset（要 GitHub Pro）。真正能卡死「只有你能改远程」的，是协作者角色。

当前仓库里只有你（`rehtd`）是协作者，别人现在本来就推不了。以后加人必须发 **Read**。

### 加同学（只读）

1. 打开 https://github.com/rehtd/course-translate/settings/access  
   （仓库 → **Settings** → **Collaborators**，左侧 Collaborators and teams）
2. **Add people**，输入同学的 GitHub 用户名
3. 角色选 **Read**（不要选 Write / Maintain / Admin）
4. 发出邀请。同学接受后可以 clone / pull，`git push` 会被 GitHub 拒绝

命令行等价（把 `USERNAME` 换成同学用户名）：

```bash
gh api -X PUT repos/rehtd/course-translate/collaborators/USERNAME -f permission=pull
```

`pull` = Read。不要用 `push` 或 `admin`。

### 已经加错过

同一页，同学右边的角色下拉改成 **Read**，或：

```bash
gh api -X PUT repos/rehtd/course-translate/collaborators/USERNAME -f permission=pull
```

删掉协作：那一行 **Remove**。

### 同学这边

他们只能拉。Agent 也不要帮他们 `git push`。本机 `.env`、录音、`data/` 已被 ignore，即使误 push 也不会带上 Key 和录音。


## 分支

- `main`：可在 macOS 上安装后上课用的源码
- Windows 适配：从 `main` 拉 `feat/windows`，做完再开 Pull Request，不要把半成品直接推 `main`
- 提交说明写清为什么改，一两句即可

## 不要提交

| 路径 | 原因 |
|------|------|
| `.env` | 真实 API Key |
| `data/` | 录音、SQLite、本机 Obsidian 路径、日志 |
| `*.wav` / `*.m4a` | 课堂原声 |
| `.venv/`、`__pycache__/` | 本机环境 |
| `同传课堂.app/` | 本机图标包；启动逻辑在 `启动同传课堂.command` 和 `scripts/macos_launch.sh` |

模板用 [`.env.example`](../.env.example)。每人自己 `cp .env.example .env` 并填自己的 Key。给新使用者看 [USAGE.md](USAGE.md)。

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
