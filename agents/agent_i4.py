"""
agents/agent_i4.py — AgentI4: Signal engine with 60-second async polling loop.

Responsibilities:
  - Fetch 5-min OHLCV candles for all watchlist symbols each cycle
  - Delegate position monitoring to AgentI6
  - Evaluate entry signals (GAP_AND_GO, ORB_BREAKOUT, GAP_FILL, VWAP_RECLAIM)
  - Apply ORB level override once 09:30 IST is reached
  - Force squareoff all positions when loop exits at 15:15 IST

Entry window: 09:30 IST – 14:00 IST
Loop runs until 15:15 IST, then terminates.
"""

from __future__ import annotations

import asyncio
import datetime
import time

import pytz
import yfinance as yf
import pandas as pd

from agents.agent_i6 import AgentI6
from agents.models import WatchlistEntry
from data.indicators import Indicators
from config import config
from utils.logger import setup_logger
from utils.telegram import notifier
from utils.decision_logger import dlog

logger = setup_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class AgentI4:
    """
    Signal engine: polls market data every 60 seconds and drives execution.

    Lifecycle:
      1. Wait for watchlist_ready_event (set by pre-market agents)
      2. Poll every 60 s until 15:15 IST
      3. On each cycle: fetch candles → monitor positions → check entries → apply ORB
      4. Force squareoff when loop exits
    """

    def __init__(self, watchlist: list) -> None:
        self.watchlist_map: dict[str, WatchlistEntry] = {
            e.symbol: e for e in watchlist
        }
        self._squaredoff: bool = False
        self._orb_set: bool = False
        self.circuit_set: set[str] = set()
        self.monitor = AgentI6()

    # ------------------------------------------------------------------
    # Batch data fetch
    # ------------------------------------------------------------------

    def _fetch_batch(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """
        Fetch 5-min candles for all symbols in one yf.download() call.

        Rate-limit guard: always sleeps 0.2 s before the network call.

        Multi-ticker download returns MultiIndex columns; single-ticker returns
        flat columns. Both cases are handled.

        Returns:
            dict[str, pd.DataFrame] — empty DataFrame for any symbol with no data.
        """
        if not symbols:
            return {}

        time.sleep(0.2)  # rate-limit guard (community consensus minimum)

        raw = yf.download(
            symbols,
            period="1d",
            interval="5m",
            prepost=False,
            auto_adjust=False,
            progress=False,
        )

        if raw.empty:
            return {s: pd.DataFrame() for s in symbols}

        # Single ticker: flat column index, no .xs() needed
        if len(symbols) == 1:
            return {symbols[0]: raw}

        # Multi-ticker: MultiIndex columns (metric, symbol) → slice per symbol
        result: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                result[sym] = raw.xs(sym, axis=1, level=1)
            except KeyError:
                result[sym] = pd.DataFrame()

        return result

    # ------------------------------------------------------------------
    # ORB level override (applied once, after 09:30 IST)
    # ------------------------------------------------------------------

    def _maybe_apply_orb_override(
        self,
        candles_map: dict[str, pd.DataFrame],
        current_time: datetime.datetime,
    ) -> None:
        """
        Compute ORB high/low from actual 5-min candles and update entry_trigger
        for all ORB_BREAKOUT symbols in the watchlist map.

        Runs at most once per session (guarded by self._orb_set).
        Only triggers after 09:30 IST.
        """
        orb_threshold = current_time.replace(
            hour=9, minute=30, second=0, microsecond=0
        )
        if self._orb_set or current_time < orb_threshold:
            return

        self._orb_set = True
        logger.info("AgentI4: applying ORB level override")

        for sym, entry in self.watchlist_map.items():
            if entry.strategy != "ORB_BREAKOUT":
                continue

            df = candles_map.get(sym, pd.DataFrame())
            if df.empty or len(df) < 3:
                logger.debug(
                    "ORB override skipped for %s — insufficient candles (%d)",
                    sym,
                    len(df),
                )
                continue

            orb_high, orb_low = Indicators.orb(df)

            if orb_high and orb_high > 0:
                logger.info(
                    "ORB override %s: entry_trigger %.2f → %.2f",
                    sym,
                    entry.entry_trigger,
                    orb_high,
                )
                entry.entry_trigger = orb_high

    # ------------------------------------------------------------------
    # Force squareoff
    # ------------------------------------------------------------------

    def force_squareoff_all(
        self,
        portfolio,
        current_prices: dict[str, float],
    ) -> None:
        """
        Close all open positions at end of session.

        Idempotent: second call logs and returns immediately.

        Args:
            portfolio:       PaperPortfolio instance.
            current_prices:  dict[str, float] — falls back to entry_price if missing.
        """
        if self._squaredoff:
            logger.info(
                "AgentI4.force_squareoff_all: already executed — skipping"
            )
            return

        self._squaredoff = True
        summary = portfolio.get_portfolio_summary()

        for pos in summary.get("positions", []):
            sym = pos["symbol"]
            price = current_prices.get(sym, pos["entry_price"])
            portfolio.sell(sym, price, pos["qty"], "FORCE_SQUAREOFF")
            notifier.send_squareoff(sym, price, pos["qty"])

        logger.info("AgentI4: force squareoff complete")

    # ------------------------------------------------------------------
    # Entry signal evaluation
    # ------------------------------------------------------------------

    def _check_entries(
        self,
        candles_map: dict[str, pd.DataFrame],
        portfolio,
        current_time: datetime.datetime,
        order_manager,
    ) -> None:
        """
        Evaluate all watchlist entries for entry signals and execute buys.

        Removes a symbol from watchlist_map once a buy is executed (prevents
        re-evaluation on subsequent cycles).
        """
        entry_start = current_time.replace(
            hour=9, minute=30, second=0, microsecond=0
        )
        entry_cutoff = current_time.replace(
            hour=14, minute=0, second=0, microsecond=0
        )
        can_buy = entry_start <= current_time <= entry_cutoff

        summary = portfolio.get_portfolio_summary()
        open_symbols = {p["symbol"] for p in summary.get("positions", [])}

        # Iterate over a snapshot to allow safe deletion during loop
        for sym in list(self.watchlist_map.keys()):
            # Skip circuit-hit symbols
            if sym in self.circuit_set:
                continue

            # Skip already-open positions
            if sym in open_symbols:
                continue

            entry = self.watchlist_map[sym]

            # Resolve current price
            df = candles_map.get(sym, pd.DataFrame())
            if df is None or df.empty:
                continue

            try:
                current_price = float(df["Close"].iloc[-1])
            except Exception:
                continue

            # Strategy-specific signal
            strategy = entry.strategy
            if strategy == "GAP_AND_GO":
                signal = current_price >= entry.entry_trigger
            elif strategy == "ORB_BREAKOUT":
                signal = current_price >= entry.entry_trigger
            elif strategy == "VWAP_RECLAIM":
                signal = current_price >= entry.entry_trigger
            elif strategy == "GAP_FILL":
                signal = current_price <= entry.entry_trigger
            else:
                signal = False

            if not signal:
                continue

            if not can_buy:
                logger.debug(
                    "Signal for %s outside entry window — skipping", sym
                )
                continue

            # Quantity sizing
            if order_manager is not None:
                qty = order_manager.calculate_quantity(
                    current_price, entry.stop_loss
                )
            else:
                qty = 1

            if qty <= 0:
                logger.debug(
                    "BUY SKIPPED %s — qty=0 (entry=%.2f sl=%.2f)",
                    sym, current_price, entry.stop_loss,
                )
                continue

            success = portfolio.buy(
                sym,
                current_price,
                qty,
                entry.stop_loss,
                entry.target,
                entry.strategy,
            )

            if success:
                del self.watchlist_map[sym]
                logger.info(
                    "BUY %s at %.2f qty=%d strategy=%s",
                    sym, current_price, qty, strategy,
                )
                rr = round((entry.target - current_price) / max(current_price - entry.stop_loss, 0.01), 2)
                dlog.buy_decision(
                    symbol=sym,
                    strategy=strategy,
                    entry_price=current_price,
                    stop_loss=entry.stop_loss,
                    target=entry.target,
                    qty=qty,
                    rr_ratio=rr,
                    gap_pct=entry.gap_pct,
                    market_bias="UNKNOWN",  # bias logged separately by AgentI0
                    trigger_condition=f"price Rs{current_price:.2f} crossed entry_trigger Rs{entry.entry_trigger:.2f}",
                )
                notifier.send_buy(
                    sym, current_price, qty, strategy,
                    entry.stop_loss, entry.target,
                )

    # ------------------------------------------------------------------
    # Single polling cycle
    # ------------------------------------------------------------------

    async def _run_cycle(
        self,
        portfolio,
        current_time: datetime.datetime,
        order_manager,
    ) -> None:
        """
        One 60-second polling cycle:
          1. Fetch 5-min candles for all watchlist symbols
          2. Monitor open positions (exits, trailing SL) via AgentI6
          3. Check entry signals
          4. Apply ORB override (once, after 09:30)
        """
        candles_map = self._fetch_batch(list(self.watchlist_map.keys()))

        self.monitor.monitor_positions(
            portfolio,
            self.watchlist_map,
            candles_map,
            current_time,
            self.circuit_set,
        )

        self._check_entries(candles_map, portfolio, current_time, order_manager)
        self._maybe_apply_orb_override(candles_map, current_time)

    # ------------------------------------------------------------------
    # Main async loop
    # ------------------------------------------------------------------

    async def run(
        self,
        watchlist,
        portfolio,
        watchlist_ready_event,
        order_manager=None,
    ) -> None:
        """
        Main intraday loop. Waits for watchlist_ready_event, then polls every
        60 seconds until 15:15 IST, then force-squares off all positions.

        Args:
            watchlist:             list[WatchlistEntry] (may differ from __init__ list).
            portfolio:             PaperPortfolio instance.
            watchlist_ready_event: asyncio.Event — set by pre-market pipeline.
            order_manager:         Optional OrderManager for quantity sizing.
        """
        await watchlist_ready_event.wait()
        logger.info("AgentI4: watchlist ready — starting market session loop")

        first_cycle = True
        while True:
            # Run the first cycle immediately (no sleep) to catch opening-range signals.
            # Subsequent cycles sleep 60 s between polls.
            if first_cycle:
                first_cycle = False
            else:
                await asyncio.sleep(60)

            current_time = datetime.datetime.now(IST)
            session_end = current_time.replace(
                hour=15, minute=15, second=0, microsecond=0
            )

            if current_time >= session_end:
                break

            try:
                await self._run_cycle(portfolio, current_time, order_manager)
            except Exception as e:
                logge