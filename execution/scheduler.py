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
import os
import subprocess
import sys
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
        self._bias = None
        self._candidate_pool: list = []
        logger.info(f"NexusTrader initialized (dry_run={dry_run})")

    # ------------------------------------------------------------------
    # Upstox Auth (08:00 IST)
    # ------------------------------------------------------------------
    def refresh_upstox_token(self) -> None:
        """Automated headless login to Upstox to refresh access token."""
        if self.dry_run:
            logger.info("DRY-RUN mode — skipping automated Upstox auth")
            return
            
        try:
            logger.info("Executing upstox_auth.py to refresh access token...")
            
            # Get the absolute path to upstox_auth.py relative to this file
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            upstox_script = os.path.join(project_root, "utils", "upstox_auth.py")
            
            process = subprocess.run(
                [sys.executable, upstox_script],
                capture_output=True,
                text=True
            )

            if process.returncode == 0:
                logger.info("Successfully refreshed Upstox access token via script.")
            else:
                logger.error("Failed to refresh Upstox token. Pre-market may fail.")
                notifier.send_error(
                    "Upstox Token Refresh Failed",
                    f"upstox_auth.py exited {process.returncode}: "
                    f"{process.stderr[-500:] if process.stderr else 'no stderr'}",
                )
        except Exception as e:
            logger.error(f"Error during Upstox token refresh: {e}")
            notifier.send_error("Upstox Token Refresh Failed", str(e))

    # ------------------------------------------------------------------
    # Pre-market pipeline  (08:30 IST)
    # ------------------------------------------------------------------

    def _run_async(self, coro_factory):
        """Run an async pipeline inside a sync APScheduler job (with the
        existing event-loop-already-running fallback)."""
        try:
            return asyncio.run(coro_factory())
        except RuntimeError:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, coro_factory())
                return future.result()

    def _print_watchlist(self) -> None:
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

    async def _gap_pipeline(self, price_source: str) -> list[WatchlistEntry]:
        """
        Shared I0→I1→(direction)→I2→I3 pipeline. price_source selects the gap
        source for AgentI1 ("preopen" at 09:08, "live" at 09:15). I3 receives a
        throwaway local event so ONLY the scheduler controls _watchlist_ready.
        """
        bias_result, raw_candidates = await asyncio.gather(
            agent_i0.run(),
            agent_i1.run(price_source=price_source),
        )

        if not raw_candidates:
            logger.warning("AgentI1 returned no candidates — NO_TRADE_DAY")
            return []

        candidates = agent_i1.apply_direction_filter(raw_candidates, bias_result)
        if not candidates:
            logger.warning("Direction filter removed all candidates — NO_TRADE_DAY")
            return []

        filtered = await agent_i2.run(candidates)
        # I3 sets the event it is handed; pass a local event so confirm remains
        # the sole setter of the real self._watchlist_ready.
        local_event = threading.Event()
        watchlist = await agent_i3.run(filtered, bias_result, local_event)
        return watchlist

    # --- 08:30 IST: bias + news/candidate-pool prep (no gaps, no event) ---
    def run_pre_market_prep(self, date_override: date | None = None) -> None:
        """
        08:30 prep: roll daily state and run I0 bias so it is cached on self for
        the later provisional/confirm jobs. Does NOT compute final gaps and does
        NOT set _watchlist_ready.
        """
        today = (
            date_override if date_override is not None
            else datetime.datetime.now(IST).date()
        )
        if not is_trading_day(today):
            logger.info(f"NSE holiday or weekend on {today} — no prep")
            return

        self._portfolio.reset_daily_state_if_new_day()

        try:
            self._bias = self._run_async(agent_i0.run)
            logger.info("Pre-market prep complete — bias cached for the day")
        except Exception as exc:
            logger.warning("Pre-market prep failed: %s", exc)
            self._bias = None

    # --- 09:08 IST: provisional watchlist from Upstox pre-open IEP (no event) ---
    def run_provisional_scan(self, date_override: date | None = None) -> None:
        """
        09:08 provisional scan from the Upstox pre-open snapshot. Builds a
        provisional self._watchlist; degrades silently (leaves watchlist for the
        09:15 confirm) if the snapshot is empty or the pipeline fails. Does NOT
        set _watchlist_ready.

        Rebinds AgentI1's module-level fetcher to a freshly constructed one so
        the current (post-08:00 refresh) Upstox token is used rather than a
        stale import-time token.
        """
        today = (
            date_override if date_override is not None
            else datetime.datetime.now(IST).date()
        )
        if not is_trading_day(today):
            logger.info(f"NSE holiday or weekend on {today} — no provisional scan")
            return

        try:
            from data.market_data import MarketDataFetcher
            agent_i1.fetcher = MarketDataFetcher()  # fresh token
            self._watchlist = self._run_async(
                lambda: self._gap_pipeline(price_source="preopen")
            )
            if self._watchlist:
                logger.info("Provisional watchlist built (%d symbols)", len(self._watchlist))
                self._print_watchlist()
            else:
                logger.info("Provisional scan produced nothing — deferring to 09:15 confirm")
        except Exception as exc:
            logger.warning("Provisional scan failed: %s — deferring to 09:15 confirm", exc)

    # --- 09:15 IST: confirm/re-rank vs first live candle; SOLE event setter ---
    def run_confirm_watchlist(self, date_override: date | None = None) -> None:
        """
        09:15 confirm: re-rank against the first live 5-min candle and finalize
        self._watchlist. This is the ONLY job that sets _watchlist_ready — on a
        holiday it still sets the event so AgentI4 never hangs.
        """
        today = (
            date_override if date_override is not None
            else datetime.datetime.now(IST).date()
        )
        if not is_trading_day(today):
            logger.info(f"NSE holiday or weekend on {today} — no trading today")
            self._watchlist_ready.set()  # unblock I4 (empty watchlist)
            return

        # Defensive: ensure daily state rolled even if prep did not run today.
        try:
            self._portfolio.reset_daily_state_if_new_day()
        except Exception as exc:
            logger.warning("Daily state reset in confirm failed: %s", exc)

        try:
            from data.market_data import MarketDataFetcher
            agent_i1.fetcher = MarketDataFetcher()  # fresh token
            self._watchlist = self._run_async(
                lambda: self._gap_pipeline(price_source="live")
            )
        except Exception as exc:
            logger.error("Confirm watchlist pipeline failed: %s", exc)
            self._watchlist = self._watchlist or []

        self._print_watchlist()

        # ALWAYS set the event (sole setter) so AgentI4 proceeds.
        self._watchlist_ready.set()

        if self._watchlist:
            self._portfolio.save_watchlist(self._watchlist)

    def run_pre_market_pipeline(self, date_override: date | None = None) -> None:
        """
        Backwards-compatible wrapper (used by `main.py --dry-run`): runs the
        full hybrid sequence prep → provisional → confirm. Confirm is the sole
        setter of _watchlist_ready.
        """
        self.run_pre_market_prep(date_override=date_override)
        self.run_provisional_scan(date_override=date_override)
        self.run_confirm_watchlist(date_override=date_override)

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
            nifty_df = fetcher._safe_fetch("^NSEI", is_intraday=False, period_days=2)
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

        # Restart after pre-market: the 08:30 job never ran in this process,
        # so the event is unset and AgentI4.run() would wait forever. The
        # market_session job only fires 09:15-15:15, after the pre-market
        # window, so an unset event here always means a restart.
        if not self._watchlist_ready.is_set():
            logger.info("Watchlist ready event not set (restart after pre-market) — setting from restored state")
            self._watchlist_ready.set()

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
            self._trader.refresh_upstox_token,
            CronTrigger(hour=8, minute=0, day_of_week="mon-fri", timezone=ist),
            id="upstox_auth", max_instances=1, replace_existing=True,
        )

        # Hybrid pre-market: prep (08:30) -> provisional (09:08) -> confirm (09:15).
        self._scheduler.add_job(
            self._trader.run_pre_market_prep,
            CronTrigger(hour=8, minute=30, day_of_week="mon-fri", timezone=ist),
            id="pre_market_prep", max_instances=1, replace_existing=True,
        )

        self._scheduler.add_job(
            self._trader.run_provisional_scan,
            CronTrigger(hour=9, minute=8, day_of_week="mon-fri", timezone=ist),
            id="provisional_scan", max_instances=1, replace_existing=True,
        )

        self._scheduler.add_job(
            self._trader.run_confirm_watchlist,
            CronTrigger(hour=9, minute=15, day_of_week="mon-fri", timezone=ist),
            id="confirm_watchlist", max_instances=1, replace_existing=True,
        )

        # Morning briefing at 09:16 — after confirm has built the watchlist.
        self._scheduler.add_job(
            self._trader.run_morning_briefing,
            CronTrigger(hour=9, minute=16, day_of_week="mon-fri", timezone=ist),
            id="morning_briefing", max_instances=1, replace_existing=True,
        )

        # Session starts at 09:16 (not 09:15) so confirm_watchlist runs first;
        # removes the same-minute race deterministically. AgentI4's event gate
        # is the backstop and entries still gate at 09:30 (ENTRY_START untouched).
        session_trigger = OrTrigger([
            CronTrigger(hour=9, minute="16-59", day_of_week="mon-fri", timezone=ist),
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
