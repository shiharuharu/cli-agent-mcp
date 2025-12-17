#!/bin/bash
# 同步 shared/ 到 src/cli_agent_mcp/shared/
# 用法: ./shared_sync.sh [-f]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SHARED_SRC="$SCRIPT_DIR/shared"
SHARED_DST="$SCRIPT_DIR/src/cli_agent_mcp/shared"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

if [ ! -d "$SHARED_SRC" ]; then
    echo -e "${RED}[ERROR]${NC} Source not found: $SHARED_SRC"
    exit 1
fi

# 运行测试（除非 -f）
if [ "$1" != "-f" ]; then
    echo -e "${GREEN}[INFO]${NC} Running tests..."
    cd "$SCRIPT_DIR"
    if ! python -m pytest tests/ -q; then
        echo -e "${RED}[ERROR]${NC} Tests failed!"
        exit 1
    fi
fi

# 同步
rm -rf "$SHARED_DST"
cp -r "$SHARED_SRC" "$SHARED_DST"
find "$SHARED_DST" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo -e "${GREEN}[INFO]${NC} Synced $(find "$SHARED_DST" -type f -name "*.py" | wc -l | tr -d ' ') files"
