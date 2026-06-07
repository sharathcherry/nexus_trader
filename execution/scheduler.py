"""
execution/scheduler.py — NexusTrader orchestrator + TradingScheduler

Phase 5: Wires up the full trading pipeline.

NexusTrader:
  - run_pre_market_pipeline(): I0+I1 concurrently, then I2, then I3 (08:30 IST)
  - run_market_session():      AgentI4 async polling loop (09:15 IST)
  - run_post_market_review():  AgentI9 Claude Sonnet review (15:35 IST)

TradingScheduler:
  - BackgroundScheduler with ThreadPoolExecutor(max_workers=1)
  - max_instances=1 on every add_job() call
  - IST timezone, Mon-Fri schedule

Decision refs: 05-CONTEXT.md
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
from datetime import date
import threading

import pytz
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from tabulate import tabulate

from agents import agent_i0, agent_i1, agent_i2, agent_i3
from agents.agent_i4 import AgentI4
from agents.agent_i9 import AgentI9
from agents.models import WatchlistEntry
from config import config
from execution.order_manager import OrderManager
from execution.portfolio import PaperPortfolio
from utils.logger import setup_logger
from utils.telegram import notifier, bot as telegram_bot

logger = setup_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

def is_trading_day(d: date) -> bool:
    """Return True if d is a weekday and not an NSE holiday."""
    return config.is_trading_day(d)


# ---------------------------------------------------------------------------
# NexusTrader
# ---------------------------------------------------------------------------


class NexusTrader:
    """
    Top-level orchestrator. Wires I0→I1→I2→I3 pre-market pipeline,
    AgentI4 market session loop, and AgentI9 post-market review.
    """

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._portfolio = PaperPortfolio()
        self._order_manager = OrderManager(self._portfolio)
        self._watchlist_ready = threading.Event()
        self._watchlist: list[WatchlistEntry] = []
        logger.info(f"NexusTrader initialized (dry_run={dry_run})")

    # ------------------------------------------------------------------
    # Pre-market pipeline  (08:30 IST)
    # ------------------------------------------------------------------

    def run_pre_market_pipeline(self, date_override: date | None = None) -> None:
        """
        Run agents I0+I1 concurrently, then I2, then I3, and build the watchlist.

        Clears the watchlist_ready event first so a re-run on the same instance
        works correctly (e.g. tests, dry-run).
        """
        today = (
            date_override
            if date_override is not None
            else datetime.datetime.now(IST).date()
        )

        if not is_trading_day(today):
            logger.info(f"NSE holiday or weekend on {today} — no trading today")
            self._watchlist_ready.set()  # unblock I4 (will find empty watchlist)
            return

        async def _pipeline() -> list[WatchlistEntry]:
            # I0 and I1 run concurrently
            bias_result, raw_candidates = await asyncio.gather(
                agent_i0.run(),
                agent_i1.run(),
            )

            if not raw_candidates:
                logger.warning("AgentI1 returned no candidates — NO_TRADE_DAY")
                return []

            # Direction filter (sync call — returns a list)
            candidates = agent_i1.apply_direction_filter(raw_candidates, bias_result)

            if not candidates:
                logger.warning("Direction filter removed all candidates — NO_TRADE_DAY")
                return []

            # I2 then I3 sequential
            filtered = await agent_i2.run(candidates)
            watchlist = await agent_i3.run(filtered, bias_result, self._watchlist_ready)
            return watchlist

        try:
            self._watchlist = asyncio.run(_pipeline())
        except RuntimeError:
            # Event loop already running — offload to a fresh thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, _pipeline())
                self._watchlist = future.result()

        # Print watchlist table
        if self._watchlist:
            rows = [
                [
                    e.symbol,
                    f"{e.gap_pct:.2f}%",
                    e.strategy,
                    f"{e.rr_ratio:.2f}",
                    e.catalyst_type,
                ]
                for e in self._watchlist
            ]
            print(
                tabulate(
                    rows,
                    headers=["Symbol", "Gap%", "Strategy", "R:R", "Catalyst"],
                    tablefmt="grid",
                )
            )
        else:
            logger.info("Watchlist empty — no trades today")

        # Ensure the event is always set (agent_i3.run sets it, but guard here
        # in case the watchlist came back empty without calling I3)
        if not self._watchlist_ready.is_set():
            self._watchlist_ready.set()

        # Save watchlist to portfolio DB for restart resilience
        if self._watchlist:
            self._portfolio.save_watchlist(self._watchlist)

    # ------------------------------------------------------------------
    # Morning briefing  (08:45 IST)
    # ------------------------------------------------------------------

    def run_morning_briefing(self) -> None:
        """Send Telegram briefing with today's watchlist and market bias."""
        try:
            bias = "UNKNOWN"
            # Try to read bias from decision log or just use watchlist count
            from data.market_data import MarketDataFetcher
            fetcher = MarketDataFetcher()
            nifty_df = fetcher._safe_fetch("^NSEI", period="2d", interval="1d")
            if not nifty_df.empty and len(nifty_df) >= 2:
                prev_close = float(nifty_df["Close"].iloc[-2])
                last_close = float(nifty_df["Close"].iloc[-1])
                chg = (last_close - prev_close) / prev_close * 100
                bias = "BULLISH" if chg > 0.3 else "BEARISH" if chg < -0.3 else "NEUTRAL"

            notifier.send_morning_briefing(
                watchlist=self._watchlist,
                bias=bias,
                capital=self._portfolio.capital,
            )
        except Exception as exc:
            logger.warning("Morning briefing failed: %s", exc)

    # ------------------------------------------------------------------
    # Market session  (09:15 IST)
    # ------------------------------------------------------------------

    def run_market_session(self) -> None:
        """
        Start AgentI4 async polling loop.

        Waits for watchlist_ready event before entering the loop.
        """
        if self.dry_run:
            logger.info("DRY-RUN mode — skipping live market session")
            return

        # Try to restore watchlist from DB on restart
        if not self._watchlist:
            self._watchlist = self._portfolio.load_watchlist()
            if self._watchlist:
                logger.info("Restored watchlist from database: %d symbols", len(self._watchlist))

        agent_i4 = AgentI4(self._watchlist)
        notifier.send_market_open(len(self._watchlist), self._portfolio.capital)

        async def _session() -> None:
            await agent_i4.run(
                self._watchlist,
                self._portfolio,
                self._watchlist_ready,
                self._order_manager,
            )

        try:
            asyncio.run(_session())
        except RuntimeError:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, _session())
                future.result()

    # ------------------------------------------------------------------
    # Post-market review  (15:35 IST)
    # ------------------------------------------------------------------

    def run_post_market_review(self) -> None:
        """Run AgentI9 Claude Sonnet review after market close and backup DB."""
        reviewer = AgentI9(self._portfolio)
        reviewer.run()

        # Daily backup of portfolio.db
        try:
            import shutil
            from pathlib import Path
            db_file = Path("execution/portfolio.db")
            if db_file.exists():
                backup_dir = Path("backups")
                backup_dir.mkdir(exist_ok=True)
                today_str = datetime.datetime.now(IST).strftime("%Y%m%d")
                shutil.copy2(db_file, backup_dir / f"portfolio_{today_str}.db")
                logger.info(f"Database backed up to backups/portfolio_{today_str}.db")
        except Exception as e:
            logger.error("Failed to backup portfolio database: %s", e)


# ---------------------------------------------------------------------------
# TradingScheduler
# ---------------------------------------------------------------------------


class TradingScheduler:
    """
    APScheduler BackgroundScheduler wired to IST, Mon-Fri trading calendar.

    Jobs:
      pre_market    — 08:30 IST, Mon-Fri
      market_session — every 60 s, 09:15–15:15 IST, Mon-Fri
      post_market   — 15:35 IST, Mon-Fri
    """

    def __init__(self, nexus_trader: NexusTrader) -> None:
        self._trader = nexus_trader
        executors = {"default": ThreadPoolExecutor(max_workers=1)}
        self._scheduler = BackgroundScheduler(executors=executors, timezone=IST)
        self._add_jobs()

    def _add_jobs(self) -> None:
        ist = IST

        self._scheduler.add_job(
            self._trader.run_pre_market_pipeline,
            CronTrigger(hour=8, minute=30, day_of_week="mon-fri", timezone=ist),
            id="pre_market", max_instances=1, replace_existing=True,
        )

        self._scheduler.add_job(
            self._trader.run_morning_briefing,
            CronTrigger(hour=8, minute=45, day_of_week="mon-fri", timezone=ist),
            id="morning_briefing", max_instances=1, replace_existing=True,
        )

        session_trigger = OrTrigger([
            CronTrigger(hour=9, minute="15-59", day_of_week="mon-fri", timezone=ist),
            CronTrigger(hour="10-14", minute="*", day_of_week="mon-fri", timezone=ist),
            CronTrigger(hour=15, minute="0-15", day_of_week="mon-fri", timezone=ist),
        ])
        self._scheduler.add_job(
            self._trader.run_market_session,
            session_trigger,
            id="market_session", max_instances=1, replace_existing=True,
        )

        self._scheduler.add_job(
            self._trader.run_post_market_review,
            CronTrigger(hour=15, minute=35, day_of_week="mon-fri", timezone=ist),
            id="post_market", max_instances=1, replace_existing=True,
        )

    def start(self) -> None:
        self._scheduler.start()
        telegram_bot.start()
        logger.info("TradingScheduler started -- IST timezone, Mon-Fri schedule")

    def shutdown(self, wait: bool = True) -> None:
        telegram_bot.stop()
        self._scheduler.shutdown(wait=wait)
        logger.info("TradingScheduler stopped")
