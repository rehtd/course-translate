# 发给 WorkBuddy 的提示词

推荐用本机 [WorkBuddy](https://www.codebuddy.cn/work/)（新手好上手；每天可领 100 积分）。打开克隆下来的文件夹，把模型切成 **DeepSeek V4 Flash**，再把下面代码块**整段复制**发给它。不要只说「帮我装一下」却不给这段提示词。

自己准备：macOS 13+（`main`）或 Windows 10/11（`feat/windows`）、Python 3.11+、至少一种翻译凭证。不要拷贝别人的 `.env` / `.venv` / `data/`。不要把 Key 发给助手：放到它创建的 `keys-inbox/` 里，**文件名写清哪家、哪一项**。上课任选一种即可；课后「计入笔记」才需要 DeepSeek。装好后它会带你测窗口能不能用；以后可再让它做一个启动程序放到「应用程序」。

`main` 是已测过的上课版，作者不会再往里面加自己后来的功能。**默认界面和笔记是按作者本人习惯做的**（尤其是 Obsidian 课节页 + 概念卡）。不合用就让助手按你的方式改本机副本，不必等仓库更新。

同一段也在 [README](../README.md)。改这一段时两处一起改。

---

```
角色：编码助手。任务：按公开仓库在使用者面前这台电脑上部署「同传课堂」，并按仓库手册引导完成上课操作。推荐使用者用本机 WorkBuddy（https://www.codebuddy.cn/work/），模型切 DeepSeek V4 Flash。不要用网页云端 Agent；终端即使显示 Linux 也是沙箱，不要按 Ubuntu 安装。

仓库：https://github.com/rehtd/course-translate.git
分支：Windows 必须用 feat/windows（git clone -b feat/windows https://github.com/rehtd/course-translate.git）。macOS 用 main。main 是已测过的上课版，不要把作者未进 main 的功能当成仓库自带。
范围：麦克风采集 → 本地 Whisper 识别 → 机器翻译 → 主窗口上英下中对照 + 底部英文悬浮字幕；课后可写入 Obsidian。feat/windows 只换系统壳，不要重写识别/翻译。仓库默认体验按作者本人上课与笔记习惯设计，尤其是计入笔记。装好后按使用者习惯改本机副本（换笔记格式、接到自己的库都可以），禁止 git push。

权威文档：
1. docs/USAGE.md — 环境、依赖、密钥、启动、麦克风授权
2. Windows 另见 docs/WINDOWS.md（仅 feat/windows 分支有）
3. 窗口可打开之后：docs/AGENT_GUIDE.md — 界面引导（先读操作总表）

策略：
- Git：禁止 git add .；禁止 git push。不要提交 .env、data/、录音、keys-inbox/。
- 密钥：不要让使用者把 Key 发到聊天里，也不要在对话中复述。在仓库创建 keys-inbox/（已 gitignore），写入说明.txt，列出各家要填什么、去哪申请、建议文件名。使用者把文本放进该文件夹，文件名必须写清哪家、哪一项，例如：
  - deepseek-api-key.txt（只要 API Key）
  - dashscope-api-key.txt（阿里百炼，只要 API Key）
  - tencent-secret-id.txt 与 tencent-secret-key.txt
  - baidu-app-id.txt 与 baidu-secret.txt
  - aliyun-access-key-id.txt 与 aliyun-access-key-secret.txt
  放好后告诉你，你只改 .env 对应行。用完可删 keys-inbox 里的密钥文件。
  各家字段（上课填一种即可；计入笔记才要 DeepSeek）：
  - DeepSeek：只要 API Key。https://platform.deepseek.com/usage
  - 阿里百炼：只要 API Key。https://bailian.console.aliyun.com
  - 腾讯云：SecretId + SecretKey。https://cloud.tencent.com/product/tmt
  - 百度：APP ID + Secret。https://fanyi-api.baidu.com
  - 阿里云机器翻译：AccessKey ID + AccessKey Secret。https://www.aliyun.com/product/ai/alimt
  - Ollama：不用云 Key，设 TRANSLATE_PROVIDER=ollama
  腾讯 / 百度 / 阿里机器翻译申请步骤：https://blog.csdn.net/weixin_44253490/article/details/126365385

执行顺序：
1. Windows 确认当前是 feat/windows。按 docs/USAGE.md 安装依赖。创建 keys-inbox/ 并写说明，等使用者放好密钥文本后再写入 .env、启动，直到主窗口可打开。
2. 冒烟：引导新建课程 → 新建一节课 → 对着麦克风说几句英文。确认底部英文字幕在动、主窗口中文有译文（可慢几秒）。第一次识别会下载 Whisper，需要联网。
3. 按 docs/AGENT_GUIDE.md 引导其余界面（先读操作总表）。
4. 窗口能用之后，若使用者要入口：macOS 可做本机启动器放到「应用程序」或 Dock（不要提交进 Git，不要做成安装包）；Windows 用仓库里的 启动同传课堂.vbs 或 .bat。

引导约定：
- Agent 执行终端命令、说明按钮与下一步；点击界面、选择路径由使用者完成。
- 一次只给出一步，待使用者确认后再继续。
- 系统弹出麦克风授权时，提示使用者点「允许」。
- 课间引导暂停，不要结束。录制中不要引导切换课程、课节或翻译引擎。
```
