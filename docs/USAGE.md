# 使用说明（人 + Agent）

同传课堂：麦克风 → 本地 Whisper → 翻译 → 主窗口英中对照 + 底部英文悬浮字幕。课后可写入 Obsidian。

仓库是公开的：`git clone https://github.com/rehtd/course-translate.git`。任何人都能拉，**不要 `git push`**（只有仓库主人能推）。

同学：把 [README](../README.md) 或 [AGENT_PROMPT.md](AGENT_PROMPT.md) 里的提示词**整段**发给编码 Agent，不要只说「帮我装一下」。人准备 Python 3.11+、至少一种翻译 Key（腾讯/百度/阿里/百炼/DeepSeek 均可）、麦克风权限。不要做成安装包给人下载。不要拷贝**别人的** `.env` / `.venv` / `data/`。把 Key 发给 Agent 或让它写入本地 `.env` 时，Agent 应该帮写。

---

## 密钥（必读）

- 启动只要有 **至少一种** 翻译配置：腾讯云、百度、阿里机器翻译、阿里百炼、DeepSeek，或在 `.env` 设 `TRANSLATE_PROVIDER=ollama`。不必先有 DeepSeek。
- 课后「计入笔记」、从本课提取术语才需要 `DEEPSEEK_API_KEY`。
- DeepSeek：打开 [用量与控制台](https://platform.deepseek.com/usage)，在同一控制台创建 **API Key**（不要用别人的，也不要向别人要）。
- 阿里云 / 百度 / 腾讯等机器翻译 Key 的申请步骤可参考：[CSDN 教程（阿里等翻译 API）](https://blog.csdn.net/weixin_44253490/article/details/126365385)。官方入口也写在 [`.env.example`](../.env.example) 各行注释里。腾讯云机器翻译可用，不吃术语表。
- 只允许出现在你电脑上的 `.env`。仓库里的 `.env.example` 全是占位符。
- **不要**拷贝别人的 `.env`，**不要**把 `.env` 发给别人或推进 Git。

---

## Agent 操作流程

这份流程不绑某一家产品。只要能读仓库、跑终端的编码 Agent 都可以。遵守 [AGENTS.md](../AGENTS.md)。装好之后，带着用户点界面请改读 [AGENT_GUIDE.md](AGENT_GUIDE.md)。

按顺序做。麦克风权限仍由使用者自己点系统设置。Key：使用者没给、也没让你写时停下来；他发来 Key 或明确要求写入本地 `.env` 时写入对应行，不要朗读、不要 commit。

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

### 3. 配置 Key

若 **不存在** `.env`：

```bash
cp .env.example .env
```

至少填一种翻译 Key（腾讯云 / 百度 / 阿里 / 百炼 / DeepSeek 均可）。课后笔记才需要 DeepSeek。申请入口见 `.env.example` 注释；机器翻译可参考 [CSDN · 阿里等翻译 API](https://blog.csdn.net/weixin_44253490/article/details/126365385)。

- 使用者**没给 Key、也没让你写**：停下来让他自己填。占位符不算。不要编造、不要用别人的 Key。不要 `git push`。
- 使用者把 Key 发给你，或明确说「写入 `.env`」「从我本机另一份 `.env` 填过来」：**写入本地 `.env` 对应行**。只改他说的项，不要整文件覆盖已有值。不要把 Key 贴回聊天，不要 commit `.env`。
- 已有 `.env` 且使用者没要求改：不要覆盖、不要主动 `cat .env`。

只打算用本机 Ollama、不填任何云 Key 时，在 `.env` 设 `TRANSLATE_PROVIDER=ollama`。

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

若弹「缺少翻译配置」，回到第 3 步，确认至少填了一种真实 Key（`.env.example` 里的占位符不算）。

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
- 「计入笔记」：英中都会送给 DeepSeek 整理（没填 DeepSeek 时按钮会说明，不影响上课）；课程/课节右键可上传 PDF 课件（要能选中文字的 PDF；扫描件抽不出字；PPT 先另存 PDF）。
- 课程右键「术语表」可手改；课节右键「从本课提取术语」勾选后才写入，**下一节课**翻译才会明显用上。
- 设置里课堂翻译选 DeepSeek / 百炼 / Ollama，术语表才会写进译文；腾讯、百度、阿里机器翻译吃不进去。

### 8. Agent 禁止做的事

- `git add .`、提交 `.env` / `data/` / 录音，以及 **`git push` 到这个仓库**。
- 把 Key 写进聊天或会进 Git 的文件。用户明确要求时可以改本地 `.env`，不要复述、不要 commit。
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

编辑 `.env` 至少填一种翻译 Key，然后 `python main.py`。上课步骤同第 6 节。课后笔记另需 DeepSeek。

---

## 翻译引擎怎么选

设置里的「翻译引擎」只管**课上右侧中文译文**（定稿入库的中文也走它）。英文识别是本地 Whisper，笔记整理始终走 DeepSeek，都不看这个选项。

不必用 DeepSeek 才能上课。设置里选了某引擎但没填 Key 时，会临时用已填写的其它引擎（不自动选 Ollama，也不改本机设置）。录制中不能切换，下课再改，下一场生效。

术语表只有 DeepSeek / 阿里百炼 / Ollama 会写进翻译提示。

| 引擎 | 优点 | 缺点 |
|------|------|------|
| **DeepSeek** | 课堂中文最顺；吃术语表和前后句上下文；课后笔记也用它 | 要联网；按量计费；上课不是必须 |
| **阿里百炼 Qwen** | 同样吃术语表和上下文；新用户常有免费额度 | 要另申请百炼 Key；课堂用语通常不如 DeepSeek 稳 |
| **Ollama** | 本机或局域网，可断网；吃术语表；不花云端翻译费 | 先自己起 Ollama 并拉模型；Mac 上大模型往往偏慢；只打算用它时需设 `TRANSLATE_PROVIDER=ollama` |
| **腾讯云机器翻译** | 快；每月约 500 万字符额度 | 不吃术语表、不管上下文；课名/人名易乱译 |
| **百度翻译** | 机器翻译，反应快；有免费字符额度 | 不吃术语表、不管上下文；课名/人名易乱译；标准版大约每秒只能 1 个请求 |
| **阿里云机器翻译** | 和腾讯/百度同类：快、有新人额度 | 不吃术语表、不管上下文 |

百度 / 阿里 / 腾讯的申请步骤见上面「密钥」里的 CSDN 链接。百炼填 `.env` 的 `DASHSCOPE_API_KEY`；Ollama 默认本机 `http://127.0.0.1:11434/v1`。

---

## 本机数据在哪

全部在仓库下的 `data/`（Git 忽略）：转写库、录音、课件 PDF、本机设置。换电脑不会自动带上。录音不要进 Git。

Windows 还不能当稳定上课机；实时请对着麦克风说几句。
