# Agent 须知

你是编码助手即可，不限产品。

同学把 GitHub 首页或 [docs/AGENT_PROMPT.md](docs/AGENT_PROMPT.md) 里的提示词整段发给你之后：

- 安装、Key、禁令：[docs/USAGE.md](docs/USAGE.md)
- **有哪些操作、怎么带着用户点界面：[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)**（先读操作总表）

不要做安装包或改成「下载即用的软件」。不要打开或复述用户的 `.env`。

硬性约束：

1. 不要提交 `.env`、`data/`、录音、数据库、本机 `settings.json`。
2. 不要 `git add .`。不要打开或复述用户已有的 `.env`。
3. 不要把别人的 API Key 写进这个仓库。让使用者自己申请至少一种翻译 Key（腾讯/百度/阿里/百炼/DeepSeek 均可；[DeepSeek 控制台](https://platform.deepseek.com/usage)；机器翻译可参考 [这篇申请教程](https://blog.csdn.net/weixin_44253490/article/details/126365385)）。
4. 若本地已有 `.env`，不要覆盖。没有则 `cp .env.example .env`，然后停下来让用户自己填至少一种翻译 Key。
5. 同学和旁人的 Agent **不要 `git push`**。本地 `.env` 和 `data/` 也不会进 Git。
6. macOS 可以上课。Windows 还不能当稳定上课机。
