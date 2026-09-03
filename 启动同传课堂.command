#!/bin/zsh
# 双击打开同传课堂（Finder 首次会询问允许）。不要写死某台机器的 Python 路径。
set -euo pipefail
ROOT="${0:A:h}"
source "$ROOT/scripts/macos_launch.sh"
macos_launch "$ROOT"
