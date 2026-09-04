# 发给编码 Agent 的提示词

把下面代码块**整段复制**发给能读仓库、跑终端的编码助手（Cursor / Claude Code、Copilot 等）。不要只说「帮我装一下」却不给这段提示词。

自己准备：macOS 13+ 或 Windows 10/11、Python 3.11+（Windows 推荐 3.11 / 3.12）、至少一种翻译 Key。不要拷贝别人的 `.env` / `.venv` / `data/`。上课任选一种翻译凭证即可；课后「计入笔记」才需要 DeepSeek。Agent 会按文档安装，并一步一步带你点界面。

同一段也在 [README](../README.md)。改这一段时两处一起改。

---

```
角色：编码助手。任务：按公开仓库在本机部署「同传课堂」，并按仓库手册引导使用者完成上课操作。

仓库：https://github.com/rehtd/course-translate.git
分支：Windows 必须用 feat/windows（git clone -b feat/windows https://github.com/rehtd/course-translate.git）。macOS 用 main 即可。
范围：麦克风采集 → 本地 Whisper 识别 → 机器翻译 → 主窗口上英下中对照 + 底部英文悬浮字幕；课后可写入 Obsidian。超出此范围的架构改动、安装包分发、为 Windows 重写识别/翻译，均不做。feat/windows 只换系统壳（置顶/点穿、字体、打开笔记、麦克风权限、启动器）。

工作区：
- 当前目录含 main.py 与 docs/USAGE.md：已是本仓库。禁止再次 clone、禁止创建 *-fresh 旁路目录、禁止改动其它项目。若在 Windows 且当前不是 feat/windows：git checkout feat/windows（或 git clone -b feat/windows 到独立目录），不要把 main 当 Windows 上课版。
- 否则：仅 clone 一次到独立目录，之后只在该副本内安装与运行。

权威文档（细节以文档为准，不以训练记忆改架构）：
1. docs/USAGE.md — 环境、依赖、密钥、启动、麦克风授权
2. Windows 另见 docs/WINDOWS.md — 只说明系统壳；不要按它重写识别/翻译
3. 窗口可打开之后：docs/AGENT_GUIDE.md — 界面引导（先读操作总表）

策略：
- Git：禁止 git add .；禁止向 origin 执行 git push。
- 密钥：禁止入库、禁止在对话中复述或索要他人密钥。无明确写入指令时，不得打开或整份覆盖已有 .env；获准写入时仅改指定行，不 commit。
- 本地数据：.env、data/、录音与本机 settings.json 不提交、不随仓库分发。
- 运行时：使用仓库内本机新建的 .venv；不硬编码本机 Python 路径；不复用他人拷贝的虚拟环境。Windows 用 启动同传课堂.vbs（无黑框）或 启动同传课堂.bat，不要用 启动同传课堂.command / 同传课堂.app。

执行顺序：
1. 按上文判定工作区；已是本仓库则不要 clone。Windows 确认分支是 feat/windows。
2. 按 docs/USAGE.md 安装并启动，直到主窗口可打开。无明确写入指令时，密钥由使用者自己填。
3. 按 docs/AGENT_GUIDE.md 引导界面操作（先读操作总表）。

引导约定：
- Agent 执行终端命令、说明按钮与下一步；点击界面、选择路径由使用者完成。
- 一次只给出一步，待使用者确认后再继续。
- 系统弹出麦克风授权时，提示使用者点「允许」；不要先让使用者去系统设置里翻。
- 课间引导暂停，不要结束。录制中不要引导切换课程、课节或翻译引擎。
- 窗口打不开、缺密钥、Python 版本不够：回到 docs/USAGE.md，不要在引导手册里重做安装。
```
