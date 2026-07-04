#!/usr/bin/env bash
# 启动状态聚合服务（HTTP :8787 + Dashboard）
set -euo pipefail
HOST_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$HOST_DIR"
if ! command -v node >/dev/null 2>&1; then
  echo "需要 Node.js。macOS: brew install node" >&2
  exit 1
fi
exec node server.js
