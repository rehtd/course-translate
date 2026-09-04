# 发给编码 Agent 的提示词

同学：打开本仓库 GitHub 页，把下面代码块**整段复制**发给 Cursor / Claude Code / Copilot 等任意能读仓库、跑终端的助手。不要只说「帮我装一下」却不给仓库地址。

人自己准备：macOS 13+、Python 3.11+（系统自带 3.9 不够）、至少一种翻译 Key、麦克风权限。不要拷贝别人的 `.env` / `.venv` / `data/`。

上课不需要 DeepSeek。腾讯云、百度、阿里机器翻译、阿里百炼、DeepSeek 填一种即可。课后「计入笔记」才需要 DeepSeek。

---

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
- 不要打开、复述、覆盖已有 .env；不要把 API Key 写进仓库、聊天或别的文件。不要向我要别人的 Key。
- 上课不需要 DeepSeek。腾讯云 / 百度 / 阿里机器翻译 / 阿里百炼 / DeepSeek 填一种就能上课。课后「计入笔记」和提取术语才需要 DeepSeek。
- 本地没有 .env 则执行：cp .env.example .env ，然后立刻停下来，让我自己填至少一种翻译 Key。.env.example 里的 your- / sk-your- 占位符不算。申请入口见该文件注释；机器翻译也可看 https://blog.csdn.net/weixin_44253490/article/details/126365385 。等我说已经填好再继续。不要代填。
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
6. 若弹「缺少翻译配置」，回到第 3 步（确认填的是真实 Key，不是占位符）。第一次识别会下载 Whisper 模型，让我连网、最好下课前先跑一次。

带我用界面时：一次只引导一步，等我说「好了」再下一步。上课中途不要让我改翻译引擎或切课程/课节。课间用暂停，不要点结束。设置里把课堂翻译选成我填了 Key 的那一家（腾讯云可用）。各引擎优缺点见 docs/USAGE.md「翻译引擎怎么选」。

本应用做不到（不要教我去找）：上课改某一句译文、自动识别中英切换、用现成 wav 当麦克风再跑一遍、Windows 稳定上课。

现在从确认环境 / 克隆 / 建虚拟环境开始。Key 和麦克风权限由我自己做。
```
