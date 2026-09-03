# 使用说明（人 + Agent）

同传课堂：麦克风 → 本地 Whisper → 翻译 → 主窗口英中对照 + 底部英文悬浮字幕。课后可写入 Obsidian。

仓库是私有的。克隆前需要被加为 GitHub collaborator。

**推荐：** 打开本仓库，让 Cursor Agent 按下面「Agent 操作流程」安装。人只需要准备 Python 3.11+、自己的 DeepSeek Key、麦克风权限。

---

## 密钥（必读）

- 启动必须有 **你自己的** `DEEPSEEK_API_KEY`（笔记、术语提取、建议的课堂翻译都走 DeepSeek）。
- 申请：https://platform.deepseek.com → API keys。别人的 Key 不能用，也不要向别人要。
- 只允许出现在你电脑上的 `.env`。仓库里的 [`.env.example`](../.env.example) 全是占位符。
- **不要**拷贝别人的 `.env`，**不要**把 `.env` 发给别人或推进 Git。

---

## Agent 操作流程

按顺序做。任何一步需要 Key 或系统权限，停下来让使用者自己完成，不要代填、不要朗读 `.env`。

### 1. 确认环境

- 系统：macOS 13+（上课主路径）。Windows 先读 [WINDOWS.md](WINDOWS.md)，不要按 Mac 启动器走。
- `python3 --version` 为 **3.11 或更高**。系统自带 3.9 不够。
- 仓库根目录要有 `main.py`。

### 2. 虚拟环境与依赖

在仓库根目录：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

不要把 `.venv/` 提交进 Git。

### 3. 配置 Key（使用者自己填）

若 **不存在** `.env`：

```bash
cp .env.example .env
```

然后告诉使用者：用编辑器打开 `.env`，把 `DEEPSEEK_API_KEY=` 后面换成自己申请的 Key。**Agent 到此停止，等使用者说已经填好。**

若 **已经存在** `.env`：不要覆盖、不要 `cat .env`、不要把内容写进聊天或 commit。

其它翻译引擎（百炼 / 百度 / 腾讯 / 阿里 / Ollama）可以后再填。上课建议 DeepSeek。腾讯在设置里仍标「待修」，课上不要选。

### 4. 麦克风

macOS：系统设置 → 隐私与安全性 → 麦克风 → 允许终端 / Cursor / 「同传课堂」（看你怎么启动）。

第一次开录若失败，按弹窗提示勾权限后 **完全退出再打开**。

### 5. 启动

任选一种：

```bash
source .venv/bin/activate
python main.py
```

或在 Finder 双击仓库根目录的 `启动同传课堂.command`（启动器会找 `.venv`，不写死某台机器的路径）。

若弹「未找到 DEEPSEEK_API_KEY」，回到第 3 步，不要用别人的 Key 凑合。

第一次识别会下载 Whisper 模型（体积大，缓存在用户目录，例如 `~/.cache`）。连校园网或先下完再上课。

可选：设置里指定 **Obsidian 库根目录**，课后「计入笔记」才写得进去。

### 6. 上课（教使用者，或使用者自己点）

1. 左侧选课程；没有则右键课程列表 → 新增课程。
2. 「＋ 新建一节课」。先选课再录。
3. 看底部悬浮英文；主窗口上英文、下中文（译文可以慢几秒）。
4. **课间用暂停**，不要点结束。暂停时麦克风仍在写录音文件。
5. 下课后点结束。录音较大时会问是否压成 m4a（回听仍可用）。也可以以后在课节上右键「压缩本节录音」。
6. 录制中不要切课程/课节，不要改翻译引擎。

### 7. 课后

- 点该课节：一句一块上英下中，双击回听。
- 「计入笔记」：英中都会进 Agent；课程/课节右键可上传 PDF 课件（要能选中文字的 PDF；扫描件抽不出字；PPT 先另存 PDF）。
- 课程右键「术语表」可手改；课节右键「从本课提取术语」勾选后才写入，**下一节课**翻译才会明显用上。
- 设置里课堂翻译选 DeepSeek，术语表才吃得进去。

### 8. Agent 禁止做的事

- `git add .`、`git add data`、`git add .env`、提交 wav/m4a/db。
- 把使用者 Key 写进 README、issue、PR、聊天记录。
- 为了「方便测试」把真实 `.env` 拷到另一台机器。
- 改上课识别/切句/翻译核心来「顺便」修 Windows（Windows 开 `feat/windows`）。
- 把 115 网盘或本机 `data/audio` 里的课堂录音推进 Git。

改代码后至少（macOS）：

```bash
export QT_QPA_PLATFORM=offscreen
export DEEPSEEK_API_KEY=sk-test-dummy
python tests/test_mainwindow_smoke.py
```

需要提交时：先 `git status`，确认没有 `.env` / `data/` / 音频，再按路径 `git add`。规范见 [REPO.md](REPO.md)。

---

## 人不用 Agent 时的最短路径

```bash
git clone https://github.com/rehtd/course-translate.git
cd course-translate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env` 填自己的 DeepSeek Key，然后 `python main.py`。上课步骤同第 6 节。

---

## 本机数据在哪

全部在仓库下的 `data/`（Git 忽略）：

- `subtitle.db` 课程/课节/转写
- `audio/` 录音
- `materials/` 上传的 PDF
- `settings.json` 本机 Obsidian 路径等

换电脑不会自动带上这些。录音不要进 Git。

---

## Windows

代码还没改完，不能当稳定上课机。要测回看：自己录音，或用网盘夹具（不在 Git 里）按夹具 README 放到 `data/`。实时字幕请对着麦克风说几句。适配说明：[WINDOWS.md](WINDOWS.md)。
