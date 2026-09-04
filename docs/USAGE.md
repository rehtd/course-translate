# 使用说明（安装）

同传课堂：麦克风 → 本地 Whisper → 翻译 → 主窗口英中对照 + 底部英文悬浮字幕。课后可写入 Obsidian。

仓库：`git clone https://github.com/rehtd/course-translate.git`。**不要 `git push`**。不要拷贝别人的 `.env` / `.venv` / `data/`。点界面见 [AGENT_GUIDE.md](AGENT_GUIDE.md)。

---

## 1. 环境

- macOS 13+。Windows 还不能当稳定上课机。
- `python3 --version` 为 **3.11 或更高**。系统自带 3.9 不够；不够就让使用者先装 3.11+。

## 2. 虚拟环境

在仓库根目录：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

不要把 `.venv/` 提交进 Git。

## 3. Key

启动要有 **至少一种** 真实翻译配置：腾讯云、百度、阿里机器翻译、阿里百炼、DeepSeek，或 `.env` 里 `TRANSLATE_PROVIDER=ollama`。`.env.example` 里的 `your-` / `sk-your-` 不算。

课后「计入笔记」、从本课提取术语才需要 `DEEPSEEK_API_KEY`。

申请：

- DeepSeek：[用量与控制台](https://platform.deepseek.com/usage)
- 机器翻译（腾讯 / 百度 / 阿里）：[CSDN 教程](https://blog.csdn.net/weixin_44253490/article/details/126365385)；官方入口也在 [`.env.example`](../.env.example) 注释里
- 百炼：`.env` 的 `DASHSCOPE_API_KEY`（见 `.env.example`）

若 **不存在** `.env`：

```bash
cp .env.example .env
```

- 使用者**没给 Key、也没让你写**：停下来让他自己填。不要编造、不要用别人的 Key。
- 他把 Key 发给你，或明确说写入 `.env` / 从本机另一份自己的 `.env` 填过来：只改对应行，不要整文件覆盖，不要把 Key 贴回聊天，不要 commit `.env`。
- 已有 `.env` 且没要求改：不要覆盖、不要主动打开。

只打算用 Ollama、不填云 Key 时，设 `TRANSLATE_PROVIDER=ollama`。

## 4. 启动

```bash
source .venv/bin/activate
python main.py
```

或 Finder 双击仓库根目录的 `启动同传课堂.command`（第一次可能要右键 → 打开）。

若弹「缺少翻译配置」，回到第 3 步。

第一次识别会下载 Whisper 模型（缓存在用户目录）。连网，最好下课前先跑一次。

## 5. 麦克风

应用自己向系统申请。启动后（或第一次点「新建一节课」）弹出系统对话框，点「允许」。**不要先去系统设置里翻。**

曾经点过「不允许」：用应用里的「打开麦克风设置」，打开开关后**完全退出应用再打开**（不要只关窗口）。

## 6. 翻译引擎怎么选

设置里的「翻译引擎」只管**课上中文译文**。英文识别是本地 Whisper。笔记整理始终走 DeepSeek。

不必用 DeepSeek 才能上课。选了某引擎但没填 Key 时，会临时用已填写的其它引擎（不自动选 Ollama，也不改本机设置）。录制中不能切换。

术语表只有 DeepSeek / 阿里百炼 / Ollama 会写进翻译提示。腾讯 / 百度 / 阿里机器翻译不吃术语表。

| 引擎 | 优点 | 缺点 |
|------|------|------|
| **DeepSeek** | 课堂中文最顺；吃术语表和上下文；课后笔记也用它 | 要联网；按量计费；上课不是必须 |
| **阿里百炼 Qwen** | 同样吃术语表和上下文；新用户常有免费额度 | 要另申请百炼 Key；课堂用语通常不如 DeepSeek 稳 |
| **Ollama** | 本机或局域网，可断网；吃术语表 | 先自己起 Ollama 并拉模型；Mac 上往往偏慢 |
| **腾讯云机器翻译** | 快；每月约 500 万字符额度 | 不吃术语表；课名/人名易乱译 |
| **百度翻译** | 快；有免费字符额度 | 不吃术语表；标准版大约每秒 1 个请求 |
| **阿里云机器翻译** | 和腾讯/百度同类 | 不吃术语表 |

Ollama 默认 `http://127.0.0.1:11434/v1`。

## 7. 本机数据

全部在仓库下的 `data/`（Git 忽略）：转写库、录音、课件、本机设置。换电脑不会自动带上。不要把录音推进 Git。

## Agent 不要做的

- `git add .`；提交 `.env` / `data/` / 录音；**`git push`**
- 把 Key 写进聊天或会进 Git 的文件

## 不用 Agent 时

```bash
git clone https://github.com/rehtd/course-translate.git
cd course-translate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env` 至少填一种翻译 Key，然后 `python main.py`。上课怎么点见 [AGENT_GUIDE.md](AGENT_GUIDE.md)。
