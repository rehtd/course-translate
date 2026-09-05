# 发给编码 Agent 的提示词

把下面代码块**整段复制**发给能读仓库、跑终端的编码助手（Cursor、Claude Code、Copilot 等）。用**本机**窗口，不要用云端 Agent。不要只说「帮我装一下」却不给这段提示词。

自己准备：Windows 10/11（本分支 `feat/windows`）或 macOS 13+（`main`）、Python 3.11+、至少一种翻译凭证。不要拷贝别人的 `.env` / `.venv` / `data/`。不要把 Key 发给 Agent，放到它创建的 `keys-inbox/` 里并标明是哪家。上课任选一种即可；课后「计入笔记」才需要 DeepSeek。Agent 会按文档安装，并一步一步带你点界面。

同一段也在 [README](../README.md)。改这一段时两处一起改。

---

```
角色：编码助手。任务：按公开仓库在使用者面前这台电脑上部署「同传课堂」，并按仓库手册引导完成上课操作。不要用 Cursor 云端 Agent；终端即使显示 Linux 也是沙箱，不要按 Ubuntu 安装。

仓库：https://github.com/rehtd/course-translate.git
分支：Windows 必须用 feat/windows（git clone -b feat/windows https://github.com/rehtd/course-translate.git）。macOS 用 main。
范围：麦克风采集 → 本地 Whisper 识别 → 机器翻译 → 主窗口上英下中对照 + 底部英文悬浮字幕；课后可写入 Obsidian。feat/windows 只换系统壳，不要重写识别/翻译。

权威文档：
1. docs/USAGE.md — 环境、依赖、密钥、启动、麦克风授权
2. Windows 另见 docs/WINDOWS.md（仅 feat/windows 分支有）
3. 窗口可打开之后：docs/AGENT_GUIDE.md — 界面引导（先读操作总表）

策略：
- Git：禁止 git add .；禁止 git push。不要提交 .env、data/、录音、keys-inbox/。
- 密钥：不要让使用者把 Key 发到聊天里，也不要在对话中复述。在仓库创建 keys-inbox/（已 gitignore），写入说明.txt，列出各家要填什么、去哪申请。使用者在该文件夹放文本，写明哪份是哪家、哪一项。放好后告诉 Agent，Agent 只改 .env 对应行。用完可删 keys-inbox 里的密钥文件。
  各家字段（上课填一种即可；计入笔记才要 DeepSeek）：
  - DeepSeek：只要 API Key。https://platform.deepseek.com/usage
  - 阿里百炼：只要 API Key。https://bailian.console.aliyun.com
  - 腾讯云：SecretId + SecretKey。https://cloud.tencent.com/product/tmt
  - 百度：APP ID + Secret。https://fanyi-api.baidu.com
  - 阿里云机器翻译：AccessKey ID + AccessKey Secret。https://www.aliyun.com/product/ai/alimt
  - Ollama：不用云 Key，设 TRANSLATE_PROVIDER=ollama

执行顺序：
1. Windows 确认当前是 feat/windows。按 docs/USAGE.md 安装依赖。创建 keys-inbox/ 并写说明，等使用者放好密钥文本后再写入 .env、启动，直到主窗口可打开。
2. 按 docs/AGENT_GUIDE.md 引导界面操作（先读操作总表）。

引导约定：
- Agent 执行终端命令、说明按钮与下一步；点击界面、选择路径由使用者完成。
- 一次只给出一步，待使用者确认后再继续。
- 系统弹出麦克风授权时，提示使用者点「允许」。
- 课间引导暂停，不要结束。录制中不要引导切换课程、课节或翻译引擎。
- macOS：需要的话可做 Dock / 「启动同传课堂.command」入口；启动器不要提交进 Git，不要做成安装包。
- Windows：用仓库里的 启动同传课堂.vbs 或 .bat，不要另做安装包。
```
