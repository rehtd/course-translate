# Agent 须知

你是编码助手即可，不限产品。

- 安装、Key、禁令：[docs/USAGE.md](docs/USAGE.md)
- **有哪些操作、怎么带着用户点界面：[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)**（先读操作总表）

不要做安装包或改成「下载即用的软件」。不要打开或复述用户的 `.env`。

硬性约束：

1. 不要提交 `.env`、`data/`、录音、数据库、本机 `settings.json`。
2. 不要 `git add .`。不要打开或复述用户已有的 `.env`。
3. 不要把别人的 API Key 写进这个仓库。让使用者自己去 [DeepSeek 开放平台](https://platform.deepseek.com) 申请，填进本地 `.env`。
4. 若本地已有 `.env`，不要覆盖。没有则 `cp .env.example .env`，然后停下来让用户自己填 Key。
5. macOS 主路径可以上课。Windows 适配未完成，见 [docs/WINDOWS.md](docs/WINDOWS.md)，不要假装已经能当上课机用。
