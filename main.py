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
        trader = NexusTrader(dry_run=True)
        trader.run_pre_market_pipeline(date_override=yesterday)
        sys.exit(0)

    # Live trading path
    trader = NexusTrader(dry_run=False)
    scheduler = TradingScheduler(nexus_trader=trader)
    scheduler.start()

    # Send Telegram "I'm alive" notification on every boot
    from utils.telegram import notifier
    notifier.send_startup(capital=config.CAPITAL)

    logger.info("nexus_trader running — waiting for SIGINT/SIGTERM (Ctrl+C to stop)")

    import signal

    def handle_shutdown(signum, frame) -> None:
        logger.info("Shutdown signal received (%d) — initiating graceful exit...", signum)
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    # SIGTERM is supported on UNIX and partially Windows (as CTRL_BREAK_EVENT or terminal shutdown)
    try:
        signal.signal(signal.SIGTERM, handle_shutdown)
    except ValueError:
        # Windows occasionally raises ValueError if not in main thread (which we are, but good to guard)
        pass

    shutdown_event.wait()

    logger.info("Graceful shutdown: leaving open positions in DB for restart reconciliation...")
    try:
        summary = trader._portfolio.get_portfolio_summary()
        open_positions = summary.get("positions", [])
        if open_positions:
            symbols = ", ".join(p["symbol"] for p in open_positions)
            logger.warning(
                "Shutdown with %d open position(s) left in DB: %s — "
                "they will be reconciled on restart or squared off at 15:15.",
                len(open_positions), symbols,
            )
    except Exception as e:
        logger.error("Error reading open positions during shutdown: %s", e)

    logger.info("Stopping scheduler...")
    scheduler.shutdown()
    logger.info("Shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
