#!/usr/bin/env bash
# nexus_trader run wrapper
# Usage:
#   bash run.sh            # live trading (blocks until Ctrl+C)
#   bash run.sh --dry-run  # pre-market pipeline only, then exit
#   bash run.sh --backtest # run backtester

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "[error] venv not found -- run: bash setup.sh"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "[error] .env not found -- copy .env.example and fill in your API keys"
    exit 1
fi

source venv/bin/activate

case "${1:-}" in
    --dry-run)  exec python main.py --dry-run ;;
    --backtest) shift; exec python backtest.py "$@" ;;
    "")         exec python main.py ;;
    *)          echo "Usage: bash run.sh [--dry-run | --backtest [args]]"; exit 1 ;;
esac
