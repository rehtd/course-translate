# Agent 须知

安装、Key、启动：[docs/USAGE.md](docs/USAGE.md)。点界面：[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)。同学提示词：[docs/AGENT_PROMPT.md](docs/AGENT_PROMPT.md)（与 README 代码块相同）。

- 当前目录已是本仓库（有 `main.py`、`docs/USAGE.md`）：不要再 clone，不要建 `*-fresh`，不要合并别的项目。
- 提示词从另一个文件夹的聊天发来：只 clone 一次到独立目录，只在那份里装。
- 不要 `git add .`。不要 `git push`。不要提交 `.env`、`data/`、录音。
- 不要主动打开或复述 `.env`。用户明确要求写入时只改对应行，不要把 Key 贴回聊天。
- 不要做成安装包。不要为 Windows 重写识别/翻译。
