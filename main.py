"""
main.py — nexus_trader entry point

Usage:
  python main.py              # live trading (APScheduler, waits for Ctrl+C)
  python main.py --dry-run    # run pre-market pipeline on yesterday's data, then exit
"""

from __future__ import annotations

import argparse
import sys
import threading
from datetime import timedelta

import pytz

from config import config
from execution.scheduler import NexusTrader, TradingScheduler
from utils.logger import setup_logger

logger = setup_logger(__name__)
shutdown_event = threading.Event()

NEXUS_BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗               ║
║  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝               ║
║  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗               ║
║  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║               ║
║  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║               ║
║  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝               ║
║                       TRADER v1.0                           ║
╚══════════════════════════════════════════════════════════════╝
"""


def print_banner(dry_run: bool = False) -> None:
    print(NEXUS_BANNER)
    mode = "DRY-RUN" if dry_run else "LIVE"
    print(
        f"  Mode: {mode} | Capital: ₹{config.CAPITAL:,.0f}"
        f" | Max Positions: {config.MAX_OPEN_POSITIONS}"
    )
    print(
        f"  Risk/Trade: {config.RISK_PER_TRADE_PCT * 100:.1f}%"
        f" | Min R:R: {config.MIN_RISK_REWARD}"
    )
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="nexus_trader — NSE India intraday paper trading"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run pre-market pipeline on yesterday's data and exit (no live trading)",
    )
    return parser.parse_args()


def main() -> None:
    # Ensure Unicode output works on Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    print_banner(dry_run=args.dry_run)

    if args.dry_run:
        logger.info("DRY-RUN mode: running pre-market pipeline on yesterday's data")
        ist = pytz.timezone("Asia/Kolkata")
        from datetime import datetime

        yesterday = datetime.now(ist).date() - timedelta(days=1)
        trader = NexusTrader(dry_run=False)
        trader.run_pre_market_pipeline(date_override=yesterday)
        sys.exit(0)

    # Live trading path
    trader = NexusTrader(dry_run=False)
    scheduler = TradingScheduler(nexus_trader=trader)
    scheduler.start()
    logger.info("nexus_trader running — press Ctrl+C to stop")

    try:
        shutdown_event.wait()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — shutting down gracefully")
        try:
            # Best-effort: close all open positions at current prices (empty map
            # falls back to entry_price for each position)
            trader._portfolio.force_squareoff_all({})
        except Exception:
            pass
        scheduler.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
