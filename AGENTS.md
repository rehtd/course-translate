# Agent 须知

你是编码助手即可，不限产品。

同学把 GitHub 首页或 [docs/AGENT_PROMPT.md](docs/AGENT_PROMPT.md) 里的提示词整段发给你之后：

- 安装、Key、禁令：[docs/USAGE.md](docs/USAGE.md)
- **有哪些操作、怎么带着用户点界面：[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)**（先读操作总表）

不要做安装包或改成「下载即用的软件」。不要主动打开或复述用户的 `.env`。

硬性约束：

1. 不要提交 `.env`、`data/`、录音、数据库、本机 `settings.json`。
2. 不要 `git add .`。不要主动打开或复述已有 `.env`。用户明确要求写入本地 `.env` 时，按他说的改对应行，不要把 Key 贴回聊天。
3. 不要把别人的 API Key 写进 Git。让使用者自己申请至少一种翻译 Key（腾讯/百度/阿里/百炼/DeepSeek 均可；[DeepSeek 控制台](https://platform.deepseek.com/usage)；机器翻译可参考 [这篇申请教程](https://blog.csdn.net/weixin_44253490/article/details/126365385)）。
4. 没有 `.env` 则 `cp .env.example .env`。用户没给 Key、也没让你写时：停下来让他自己填。他发来 Key，或让你从本机另一份自己的 `.env` 填过来时：写入本地 `.env`，只改他说的项，不要整文件覆盖，不要 commit。
5. 同学和旁人的 Agent **不要 `git push`**。本地 `.env` 和 `data/` 也不会进 Git。
6. macOS 可以上课。Windows 还不能当稳定上课机。
