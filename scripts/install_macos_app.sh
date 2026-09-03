#!/bin/zsh
# 把便携启动脚本装进本机 同传课堂.app（.app 本身不进 Git）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/同传课堂.app/Contents/MacOS/同传课堂"
if [[ ! -d "$ROOT/同传课堂.app/Contents" ]]; then
  print -r -- "没有 同传课堂.app，只使用 启动同传课堂.command 即可。"
  exit 0
fi
cp "$ROOT/scripts/macos_app_exec.sh" "$DEST"
chmod +x "$DEST"
# 换掉写死路径的二进制后，旧签名失效；本地 ad-hoc 签一下即可双击。
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep -s - "$ROOT/同传课堂.app" >/dev/null 2>&1 || true
fi
print -r -- "已写入 $DEST"
