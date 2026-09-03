# 同传课堂（course-translate）

课堂实时同传：麦克风 → 本地 faster-whisper → 翻译 → 主窗口对照 + 底部英文悬浮字幕。课后可整理进 Obsidian，并从课节提取术语表。

当前主界面按状态切换：

- **录制中**：主区上英文、下中文两个大框（独立滚动；翻译可以慢几秒）。悬浮字幕只跟英文。
- **回看**：一句一块，上英下中；双击回听。课间用暂停，不要点结束。

## 环境

- macOS（目前悬浮窗层级用了 AppKit；Windows 适配见 [docs/WINDOWS.md](docs/WINDOWS.md)）
- Python 3.11+
- `.env` 里至少要有 `DEEPSEEK_API_KEY`（笔记 / 术语提取始终走 DeepSeek）

## 安装（macOS）

```bash
git clone https://github.com/rehtd/course-translate.git
cd course-translate
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，填入你自己的 Key。**不要把别人的 `.env` 拷过来，也不要提交 `.env`。**

第一次跑识别会下载 Whisper 模型（体积较大，缓存在用户目录）。

```bash
python main.py
```

课间休息按暂停；下课后点结束。设置里课堂翻译建议用 **DeepSeek**（机器翻译吃不到术语表和上下文）。

## 仓库纪律

完整约定见 [docs/REPO.md](docs/REPO.md)。摘要：

- **永不提交**：`.env`、`data/`（录音、数据库、本机 settings）、`*.wav`
- 不要 `git add .`；加文件前看一眼 `git status`
- Windows 适配开分支 `feat/windows`，不要直接改 `main` 里的实验提交

## 上课怎么用

1. 左侧选课程（如 IS6335），中间「＋ 新建一节课」
2. 看悬浮英文跟读；主窗口两个框看定稿英/中
3. 课间暂停，不要结束
4. 结束后点该课节回看；需要时「计入笔记」、课程右键「术语表」

## 架构（简）

```
麦克风 → VAD 切块 → Whisper 草稿/定稿双轨 → 翻译
       → 悬浮英文字幕 + 主窗口（录制双框 / 回看对照）→ SQLite
```

本机数据在 `data/`（git 忽略）：`subtitle.db`、`audio/`、`settings.json`。
