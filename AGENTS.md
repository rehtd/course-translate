# Agent 须知

你是编码助手即可，不限产品。

- 安装、Key、禁令：[docs/USAGE.md](docs/USAGE.md)
- **有哪些操作、怎么带着用户点界面：[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)**（先读操作总表）

不要做安装包或改成「下载即用的软件」。不要打开或复述用户的 `.env`。

硬性约束：

1. 不要提交 `.env`、`data/`、录音、数据库、本机 `settings.json`。
2. 不要 `git add .`。不要打开或复述用户已有的 `.env`。
3. 不要把别人的 API Key 写进这个仓库。让使用者自己去 [DeepSeek 控制台](https://platform.deepseek.com/usage) 创建 Key。阿里/百度/腾讯等可参考 [这篇申请教程](https://blog.csdn.net/weixin_44253490/article/details/126365385)。
4. 若本地已有 `.env`，不要覆盖。没有则 `cp .env.example .env`，然后停下来让用户自己填 Key。
6. **同学的 Agent 不要 `git push` 到 origin**（https://github.com/rehtd/course-translate）。这个仓库只读协作；本地 `.env` 和 `data/` 也不会进 Git。
