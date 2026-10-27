#!/usr/bin/env bash
# 一条命令入口：找一个能跑的 python，转发给 xbloom_brew.py。
# 不带参数时 = 干跑 recipes/current.json（不连蓝牙、不需要 bleak）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 常用解释器位置，按优先级：PATH 上的 python3 → python → 项目内虚拟环境
CANDIDATES=(
  "$(command -v python3 || true)"
  "$(command -v python || true)"
  "$ROOT/.venv/bin/python"
  "$ROOT/venv/bin/python"
)

PY=""
FOUND=""
for candidate in "${CANDIDATES[@]}"; do
  [ -n "$candidate" ] && [ -x "$candidate" ] || continue
  [ -n "$FOUND" ] || FOUND="$candidate"
  if "$candidate" -c "import bleak" >/dev/null 2>&1; then PY="$candidate"; break; fi
done

# 干跑不需要蓝牙库，有解释器就够了
PY="${PY:-$FOUND}"
if [ -z "$PY" ]; then
  echo "没找到 python3。装一个 Python 3.9+ 再来；只想看参数的话，直接读 recipes/current.json。"
  exit 2
fi

if [ "$#" -eq 0 ]; then
  set -- brew --recipe "$ROOT/recipes/current.json"
fi

# 真要连机器时才检查蓝牙库，避免干跑被卡住
NEEDS_BLE=0
for arg in "$@"; do
  case "$arg" in
    --load|--start|--address|scan|check|grind|info|mode|save-slots) NEEDS_BLE=1 ;;
  esac
done

if [ "$NEEDS_BLE" -eq 1 ] && ! "$PY" -c "import bleak" >/dev/null 2>&1; then
  echo "要连机器得先装一个蓝牙库，一行命令："
  echo "  $PY -m pip install bleak"
  echo "  如果提示 externally-managed 或权限不够，就建个虚拟环境："
  echo "    python3 -m venv .venv && .venv/bin/pip install bleak"
  echo
  echo "只想先看要发什么的话，去掉 --load / --start 再跑一次。"
  exit 2
fi

exec "$PY" "$ROOT/scripts/xbloom_brew.py" "$@"
