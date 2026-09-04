# 发给编码 Agent 的提示词

把下面代码块**整段复制**发给能读仓库、跑终端的编码助手（Cursor / Claude Code / Copilot 等）。不要只说「帮我装一下」却不给这段提示词。

自己准备：macOS 13+ 或 Windows 10/11、Python 3.11+、至少一种翻译 Key。Windows 须 clone `feat/windows`。不要拷贝别人的 `.env` / `.venv` / `data/`。上课任选一种翻译凭证即可；课后「计入笔记」才需要 DeepSeek。Agent 会按文档安装，并一步一步带你点界面。

同一段也在 [README](../README.md)。改这一段时两处一起改。

---

```
角色：编码助手。任务：按公开仓库在本机部署「同传课堂」，并按仓库手册引导使用者完成上课操作。

仓库：https://github.com/rehtd/course-translate.git
分支：Windows 必须用 feat/windows（git clone -b feat/windows https://github.com/rehtd/course-translate.git）。macOS 用 main 即可。
范围：麦克风采集 → 本地 Whisper 识别 → 机器翻译 → 主窗口上英下中对照 + 底部英文悬浮字幕；课后可写入 Obsidian。超出此范围的架构改动、安装包分发、为 Windows 重写识别/翻译，均不做。feat/windows 只换系统壳。

权威文档：
1. docs/USAGE.md — 环境、依赖、密钥、启动、麦克风授权
2. Windows 另见 docs/WINDOWS.md（仅 feat/windows 分支有）
3. 窗口可打开之后：docs/AGENT_GUIDE.md — 界面引导（先读操作总表）

策略：
- Git：禁止 git add .；禁止 git push。不要提交 .env、data/、录音。
- 密钥：禁止在对话中复述。没让写就不要动 .env。
- 运行时：本机新建 .venv，不要拷别人的。Windows 用 启动同传课堂.vbs 或 .bat；macOS 用 启动同传课堂.command。不要做成安装包。

执行顺序：
1. Windows 确认分支是 feat/windows。按 docs/USAGE.md 安装并启动，直到主窗口可打开。没让写 Key 就等使用者自己填。
2. 按 docs/AGENT_GUIDE.md 引导界面操作（先读操作总表）。

引导约定：
- Agent 执行终端命令、说明按钮与下一步；点击界面、选择路径由使用者完成。
- 一次只给出一步，待使用者确认后再继续。
- 系统弹出麦克风授权时，提示使用者点「允许」。
- 课间引导暂停，不要结束。录制中不要引导切换课程、课节或翻译引擎。
- macOS：需要的话可在本机做 Dock 入口；启动器不要提交进 Git。Windows：用仓库里已有的 vbs/bat，不要另做安装包。
```
