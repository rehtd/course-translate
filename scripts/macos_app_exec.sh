#!/bin/zsh
# 同传课堂.app/Contents/MacOS/同传课堂 — 由 scripts/install_macos_app.sh 安装。
# 假定 .app 放在仓库根目录（与 main.py 同级）。
set -euo pipefail
HERE="${0:A:h}"
ROOT="${HERE:h:h:h}"
LAUNCH="$ROOT/scripts/macos_launch.sh"
if [[ ! -f "$LAUNCH" ]]; then
  osascript -e 'display dialog "请把「同传课堂.app」放在仓库根目录（和 main.py、启动同传课堂.command 一起）。" buttons {"好"} default button 1 with title "同传课堂"' >/dev/null 2>&1 || true
  exit 1
fi
source "$LAUNCH"
macos_launch "$ROOT"
