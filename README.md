# 同传课堂（course-translate）

课堂实时同传：麦克风 → 本地 faster-whisper → 翻译 → 主窗口对照 + 底部英文悬浮字幕。课后可整理进 Obsidian，并从课节提取术语表。

- **录制中**：主区上英文、下中文两个大框（独立滚动；翻译可以慢几秒）。悬浮字幕只跟英文。
- **回看**：一句一块，上英下中；双击回听。课间用暂停，不要点结束。

安装、上课：任意编码 Agent 读 **[docs/USAGE.md](docs/USAGE.md)** 和 **[docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)**。

```bash
git clone https://github.com/rehtd/course-translate.git
```

每人使用 **自己申请的** DeepSeek Key，填进本地 `.env`。不要拷贝别人的 `.env`，不要 `git push`。

## 环境

- macOS 13+（上课主路径；悬浮窗用了 AppKit）
- Python 3.11+
- 自己的 `DEEPSEEK_API_KEY`（[控制台](https://platform.deepseek.com/usage)）

**Windows**：还不能当稳定上课机（macOS 为主）。

不要提交 `.env`、`data/`、录音；不要 `git add .`；不要 `git push`。

## 上课怎么用

1. 左侧选课程（如 IS6335），中间「＋ 新建一节课」
2. 看悬浮英文跟读；主窗口两个框看定稿英/中
3. 课间暂停，不要结束
4. 结束后点该课节回看；需要时「计入笔记」、课程右键「术语表」
5. 课程右键可上传**总览 PDF**，课节右键可上传**本节课件 PDF**（计入笔记时会抽文字）

## 架构（简）

```
麦克风 → VAD 切块 → Whisper 草稿/定稿双轨 → 翻译
       → 悬浮英文字幕 + 主窗口（录制双框 / 回看对照）→ SQLite
```

本机数据在 `data/`（git 忽略）：`subtitle.db`、`audio/`、`settings.json`。
