# 被 启动同传课堂.command / 同传课堂.app 引用。
# 按顺序找解释器：仓库 .venv → 本机 WorkBuddy 环境 → PATH 上的 python3。
# 不要写死 /Users/某用户/...

macos_pick_python() {
  local root="$1"
  local p
  for p in \
    "$root/.venv/bin/python" \
    "$root/.venv/bin/python3" \
    "$HOME/.workbuddy/binaries/python/envs/live-subtitle/bin/python"
  do
    if [[ -x "$p" ]]; then
      print -r -- "$p"
      return 0
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  return 1
}

macos_launch_fail() {
  local msg="$1"
  print -r -- "$msg" >&2
  osascript -e "display dialog \"$msg\" buttons {\"好\"} default button 1 with title \"同传课堂\"" >/dev/null 2>&1 || true
  exit 1
}

macos_launch() {
  local root="$1"
  cd "$root" || macos_launch_fail "无法进入仓库目录：$root"
  if [[ ! -f "$root/main.py" ]]; then
    macos_launch_fail "仓库根目录找不到 main.py。请把启动器或同传课堂.app 放在仓库根目录。"
  fi
  local py
  py=$(macos_pick_python "$root") || macos_launch_fail "找不到 Python。请在本仓库执行：python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  if ! "$py" -c "import PySide6" >/dev/null 2>&1; then
    macos_launch_fail "当前 Python 还没装依赖（$py）。请执行：$py -m pip install -r requirements.txt"
  fi
  exec "$py" -u main.py
}
