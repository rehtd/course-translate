# 同传课堂（course-translate）

课堂实时同传：麦克风 → 本地 Whisper → 翻译 → 主窗口英中对照 + 底部英文悬浮字幕。课后可整理进 Obsidian。

- **录制中**：主区上英文、下中文两个大框（译文可以慢几秒）。悬浮字幕只跟英文。
- **回看**：一句一块上英下中，双击回听。课间用**暂停**，不要点结束。

公开仓库，任何人都能克隆。**不要 `git push`**（只有仓库主人能推）。不要拷贝别人的 `.env`。

```bash
git clone https://github.com/rehtd/course-translate.git
```

---

## 同学怎么开始

1. 一台 **macOS 13+** 电脑（Windows 还不能当稳定上课机）。
2. 安装 **Python 3.11 或更高**（macOS 自带的 3.9 不够）。
3. 自己去 [DeepSeek 控制台](https://platform.deepseek.com/usage) 申请 API Key（不要用别人的）。
4. 把**下面整段提示词**复制发给你的编码 Agent（Cursor、Claude Code、Copilot 等都可以），让它按仓库文档装并带着你点界面。

人不用 Agent 时的步骤见 [docs/USAGE.md](docs/USAGE.md)「最短路径」。Agent 装好之后怎么上课，见 [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)。

---

## 发给 Agent 的提示词（整段复制）

同一份也在 [docs/AGENT_PROMPT.md](docs/AGENT_PROMPT.md)。

```
你是编码助手，不限产品。请按这个公开仓库帮我在本机装好「同传课堂」，并按手册带着我点界面上课。

仓库：https://github.com/rehtd/course-translate.git
产品：麦克风 → 本地 Whisper → 翻译 → 主窗口上英下中 + 底部英文悬浮字幕。课后可写入 Obsidian。

克隆（若我还没有这个仓库）后，先读这三份，不要凭记忆改架构：
1. AGENTS.md
2. docs/USAGE.md（安装、Key、禁令；按第 1–5 步做）
3. docs/AGENT_GUIDE.md（有哪些操作、怎么带我点界面；先读操作总表）

硬性约束：
- 不要 git add .。不要 git push 到 origin（只有仓库主人能推；我是同学/旁人）。
- 不要打开、复述、覆盖已有 .env；不要把 API Key 写进仓库、聊天或别的文件。
- 本地没有 .env 则执行：cp .env.example .env ，然后立刻停下来，让我自己去 https://platform.deepseek.com/usage 创建 Key，填进 .env 的 DEEPSEEK_API_KEY。等我说已经填好再继续。不要代填。
- 不要提交、不要分发：.env、data/、录音、*.wav、*.m4a、数据库、本机 settings.json。
- 不要做成 dmg/exe/安装包，不要改成「下载即用」的软件。
- macOS 13+ 可以上课。Windows 还不能当稳定上课机，不要为此重写识别/翻译。
- 用本仓库里的 .venv，不要写死某台机器的 Python 路径，也不要拿别人拷来的虚拟环境。

安装（USAGE.md 第 1–5 步）：
1. 确认 python3 --version 是 3.11 或更高。系统 3.9 不够；不够就让我先装 3.11+ 再继续。
2. 在仓库根目录：python3 -m venv .venv && source .venv/bin/activate && python -m pip install -U pip && pip install -r requirements.txt
3. 按上面规则处理 .env，停下来等我填 Key。
4. 告诉我去「系统设置 → 隐私与安全性 → 麦克风」，允许终端、编辑器或 python（看实际是谁在开应用）。
5. source .venv/bin/activate && python main.py ；或装好后双击仓库根目录的「启动同传课堂.command」（Finder 第一次可能要右键 → 打开）。
6. 若弹「未找到 DEEPSEEK_API_KEY」，回到第 3 步。第一次识别会下载 Whisper 模型，让我连网、最好下课前先跑一次。

带我用界面时：一次只引导一步，等我说「好了」再下一步。上课中途不要让我改翻译引擎或切课程/课节。课间用暂停，不要点结束。课堂翻译建议 DeepSeek（吃术语表）；各引擎优缺点见 docs/USAGE.md「翻译引擎怎么选」。

本应用做不到（不要教我去找）：上课改某一句译文、自动识别中英切换、用现成 wav 当麦克风再跑一遍、Windows 稳定上课。

现在从确认环境 / 克隆 / 建虚拟环境开始。Key 和麦克风权限由我自己做。
```

---

## 人要自己做的（Agent 不会代劳）

| 事项 | 去哪 |
|------|------|
| DeepSeek API Key | [用量与控制台](https://platform.deepseek.com/usage) → 创建 Key → 写入本地 `.env` |
| 其它翻译引擎（可选） | [CSDN · 阿里等翻译 API](https://blog.csdn.net/weixin_44253490/article/details/126365385) |
| 麦克风 | 系统设置 → 隐私与安全性 → 麦克风 |
| Obsidian 笔记库 | 应用内「⚙ 设置」（不选则「计入笔记」写不进去） |

### 翻译引擎（只影响课上中文）

英文识别是本地 Whisper，笔记整理始终走 DeepSeek。上课建议 **DeepSeek**。详情见 [docs/USAGE.md](docs/USAGE.md#翻译引擎怎么选)。

| 引擎 | 优点 | 缺点 |
|------|------|------|
| DeepSeek | 课堂中文最顺；吃术语表和上下文 | 要联网、按量计费 |
| 阿里百炼 Qwen | 也吃术语表；常有免费额度 | 另申请 Key；质量通常不如 DeepSeek 稳 |
| Ollama | 可断网；吃术语表 | 要自己起服务；Mac 上往往偏慢 |
| 百度 / 阿里机器翻译 | 快、有免费额度 | 不吃术语表；课名/人名易乱译 |
| 腾讯云 | — | 待修，课上不要选 |

不要提交 `.env`、`data/`、录音；不要 `git add .`；不要 `git push`。

本机数据只在你电脑上的 `data/`（Git 忽略）。换电脑不会自动带上课节和录音。
