# 使用说明（人 + Agent）

同传课堂：麦克风 → 本地 Whisper → 翻译 → 主窗口英中对照 + 底部英文悬浮字幕。课后可写入 Obsidian。

仓库是公开的：`git clone https://github.com/rehtd/course-translate.git`。任何人都能拉，**不要 `git push`**（只有仓库主人能推）。

同学：把 [README](../README.md) 或 [AGENT_PROMPT.md](AGENT_PROMPT.md) 里的提示词**整段**发给编码 Agent，不要只说「帮我装一下」。人准备 Python 3.11+、自己的 DeepSeek Key、麦克风权限。不要做成安装包给人下载。不要拷贝别人的 `.env` / `.venv` / `data/`。

---

## 密钥（必读）

- 启动必须有 **你自己的** `DEEPSEEK_API_KEY`（笔记、术语提取、建议的课堂翻译都走 DeepSeek）。
- DeepSeek：打开 [用量与控制台](https://platform.deepseek.com/usage)，在同一控制台创建 **API Key**（不要用别人的，也不要向别人要）。
- 阿里云 / 百度 / 腾讯等机器翻译 Key 的申请步骤可参考：[CSDN 教程（阿里等翻译 API）](https://blog.csdn.net/weixin_44253490/article/details/126365385)。官方入口也写在 [`.env.example`](../.env.example) 各行注释里。上课仍建议 DeepSeek；腾讯在设置里标了待修，课上不要选。
- 只允许出现在你电脑上的 `.env`。仓库里的 `.env.example` 全是占位符。
- **不要**拷贝别人的 `.env`，**不要**把 `.env` 发给别人或推进 Git。

---

## Agent 操作流程

这份流程不绑某一家产品。只要能读仓库、跑终端的编码 Agent 都可以。遵守 [AGENTS.md](../AGENTS.md)。装好之后，带着用户点界面请改读 [AGENT_GUIDE.md](AGENT_GUIDE.md)。

按顺序做。任何一步需要 Key 或系统权限，停下来让使用者自己完成，不要代填、不要朗读 `.env`。

### 1. 确认环境

- 系统：macOS 13+（上课主路径）。Windows 还不能当稳定上课机，不要用 Mac 启动器。
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

然后告诉使用者：打开 [DeepSeek 控制台](https://platform.deepseek.com/usage) 自己申请 API Key，用编辑器打开 `.env`，把 `DEEPSEEK_API_KEY=` 后面换成自己的。**Agent 到此停止，等使用者说已经填好。不要代填，不要 `git push`。**

若还要阿里/百度/腾讯机器翻译，把这篇教程发给用户自己申请，填进 `.env` 对应行：[CSDN · 阿里等翻译 API](https://blog.csdn.net/weixin_44253490/article/details/126365385)。

若 **已经存在** `.env`：不要覆盖、不要 `cat .env`、不要把内容写进聊天或 commit。

其它翻译引擎可以后再填。上课建议 DeepSeek。腾讯在设置里标了待修，课上不要选。

### 4. 麦克风

macOS：系统设置 → 隐私与安全性 → 麦克风 → 允许终端、你用来启动的编辑器、或 `python`（看实际是谁在开应用）。

第一次开录若失败，按弹窗提示勾权限后 **完全退出再打开**。

### 5. 启动

任选一种：

```bash
source .venv/bin/activate
python main.py
```

或在 Finder 双击仓库根目录的 `启动同传课堂.command`。

若弹「未找到 DEEPSEEK_API_KEY」，回到第 3 步。

第一次识别会下载 Whisper 模型（体积大，缓存在用户目录）。连校园网或先下完再上课。

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
- 「计入笔记」：英中都会送给 DeepSeek 整理；课程/课节右键可上传 PDF 课件（要能选中文字的 PDF；扫描件抽不出字；PPT 先另存 PDF）。
- 课程右键「术语表」可手改；课节右键「从本课提取术语」勾选后才写入，**下一节课**翻译才会明显用上。
- 设置里课堂翻译选 DeepSeek，术语表才吃得进去。

### 8. Agent 禁止做的事

- `git add .`、提交 `.env` / `data/` / 录音，以及 **`git push` 到这个仓库**。
- 把使用者 Key 写进聊天或文件。不要覆盖已有 `.env`。
- 不要把应用打成安装包。不要重写识别/翻译来「修 Windows」。

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

全部在仓库下的 `data/`（Git 忽略）：转写库、录音、课件 PDF、本机设置。换电脑不会自动带上。录音不要进 Git。

Windows 还不能当稳定上课机；实时请对着麦克风说几句。
