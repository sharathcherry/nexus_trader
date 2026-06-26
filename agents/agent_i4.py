"""
agents/agent_i4.py — AgentI4: Signal engine with 60-second async polling loop.

Responsibilities:
  - Fetch 5-min OHLCV candles for all watchlist symbols each cycle
  - Delegate position monitoring to AgentI6
  - Evaluate entry signals (GAP_AND_GO, ORB_BREAKOUT, GAP_FILL, VWAP_RECLAIM, RELATIVE_STRENGTH)
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
from utils.brokerage import SLIPPAGE_PCT
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
        self.bought_symbols: set[str] = set()
        self._squaredoff: bool = False
        self._orb_set: bool = False
        self.nifty_bearish: bool = False
        self._last_nifty_check: float = 0.0
        self.circuit_set: set[str] = set()
        self._feed_blind: bool = False  # True when the data feed is degraded (most symbols empty)
        self.monitor = AgentI6()

    # ------------------------------------------------------------------
    # Batch data fetch
    # ------------------------------------------------------------------

    def _fetch_batch(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """
        Fetch 5-min candles for all symbols using MarketDataFetcher.
        Returns:
            dict[str, pd.DataFrame] — empty DataFrame for any symbol with no data.
        """
        if not symbols:
            return {}

        from data.market_data import MarketDataFetcher
        fetcher = MarketDataFetcher()
        result: dict[str, pd.DataFrame] = {}
        
        for sym in symbols:
            try:
                # Use MarketDataFetcher to handle hybrid Upstox/yfinance logic
                df = fetcher._safe_fetch(sym, is_intraday=True)
                result[sym] = df if not df.empty else pd.DataFrame()
            except Exception as e:
                logger.error("Error fetching data for %s: %s", sym, e)
                result[sym] = pd.DataFrame()
                
        return result

    # ------------------------------------------------------------------
    # Data-feed health (blind-feed detection)
    # ------------------------------------------------------------------

    def _check_feed_health(self, candles_map: dict[str, pd.DataFrame]) -> bool:
        """
        Detect a blind data feed. Upstox is the sole live source on the VM
        (yfinance is disabled there), so if most monitored symbols return no
        candles the feed is down and the session is effectively blind.

        Returns True when blind. The caller suppresses NEW entries while blind
        (never trade on stale/no data) but still runs position monitoring so any
        position that does have data can still exit. Recovers automatically.

        A loud ERROR + Telegram alert fires once on the blind->healthy edge and a
        recovery notice once on the healthy edge (deduped via self._feed_blind).
        Requires >=3 symbols to avoid false positives on a tiny watchlist.
        """
        total = len(candles_map)
        if total < 3:
            return self._feed_blind  # too small to judge; hold current state

        empty = sum(1 for df in candles_map.values() if df is None or df.empty)
        empty_rate = empty / total
        blind = empty_rate > 0.5

        if blind and not self._feed_blind:
            self._feed_blind = True
            logger.error(
                "DATA FEED BLIND: %d/%d symbols returned no candles (%.0f%%) -- "
                "pausing new entries until data recovers (check Upstox feed)",
                empty, total, empty_rate * 100,
            )
            try:
                from utils.telegram import notifier
                notifier.send_alert(
                    "DATA FEED BLIND",
                    f"{empty}/{total} symbols no data ({empty_rate*100:.0f}%). "
                    f"New entries paused -- check the Upstox feed.",
                )
            except Exception:
                pass
        elif not blind and self._feed_blind:
            self._feed_blind = False
            logger.warning(
                "DATA FEED RECOVERED: %d/%d symbols have candles -- resuming entries",
                total - empty, total,
            )
            try:
                from utils.telegram import notifier
                notifier.send_alert("DATA FEED RECOVERED", "Entries resumed.")
            except Exception:
                pass

        return blind

    # ------------------------------------------------------------------
    # ORB level override (applied once, after 09:30 IST)
    # ------------------------------------------------------------------

    def _maybe_apply_orb_override(
        self,
        candles_map: dict[str, pd.DataFrame],
        current_time: datetime.datetime,
        portfolio=None,
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
                old_trigger = entry.entry_trigger
                new_target = round(orb_high + 2.0 * entry.atr, 2)
                new_sl = round(orb_low, 2)
                denom = orb_high - new_sl
                if denom <= 0:
                    continue
                rr_ratio = (new_target - orb_high) / denom
                from config import config
                if rr_ratio < config.MIN_RR_RATIO:
                    logger.debug("ORB override %s rejected: R:R %.2f < %.2f", sym, rr_ratio, config.MIN_RR_RATIO)
                    entry.entry_trigger = float('inf')
                    continue

                logger.info(
                    "ORB override %s: trigger %.2f → %.2f, SL → %.2f, Target → %.2f",
                    sym, old_trigger, orb_high, new_sl, new_target,
                )
                entry.entry_trigger = orb_high
                entry.stop_loss = new_sl
                entry.target = new_target
                entry.rr_ratio = round(rr_ratio, 2)
                if portfolio is not None:
                    portfolio.update_watchlist_trigger(sym, orb_high)

    # ------------------------------------------------------------------
    # Nifty bearish filter
    # ------------------------------------------------------------------

    def _evaluate_nifty_filter(self) -> None:
        import time
        current_time = time.time()
        # Check every 5 minutes (300 seconds)
        if current_time - self._last_nifty_check < 300:
            return
        
        self._last_nifty_check = current_time
        try:
            from data.market_data import MarketDataFetcher
            fetcher = MarketDataFetcher()
            nifty_df = fetcher._safe_fetch("^NSEI", is_intraday=True)
            prev_close = fetcher.get_previous_close("^NSEI")
            
            if not nifty_df.empty and prev_close:
                last_close = float(nifty_df["Close"].iloc[-1])
                nifty_chg = (last_close - prev_close) / prev_close * 100
                was_bearish = self.nifty_bearish
                self.nifty_bearish = nifty_chg < -0.5
                
                if self.nifty_bearish and not was_bearish:
                    logger.warning("NIFTY BEARISH FILTER ACTIVE: %.2f%% -- blocking long setups", nifty_chg)
                    from utils.telegram import notifier
                    notifier.send_alert("Nifty Filter", f"Nifty down {nifty_chg:.2f}% -- blocking longs.")
                elif not self.nifty_bearish and was_bearish:
                    logger.info("NIFTY BEARISH FILTER CLEARED: %.2f%% -- unblocking longs", nifty_chg)
        except Exception as e:
            logger.debug("Nifty filter check failed: %s", e)

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
        portfolio.force_squareoff_all(current_prices)
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

        summary = portfolio.get_portfolio_summary()
        open_symbols = {p["symbol"] for p in summary.get("positions", [])}

        # Persistent re-entry guard. bought_symbols is in-memory only, so a
        # mid-session restart (or a fresh AgentI4 instance) loses it and the
        # system re-buys a name that already stopped out -- averaging into a
        # falling knife (observed 2026-06-23: SAIL/FIVESTAR/VBL each entered
        # twice). Pull today's CLOSED trades straight from the DB each cycle so
        # any symbol traded today, win or loss, is never re-entered.
        try:
            traded_today = {
                t["symbol"] for t in portfolio.get_daily_report().get("trades", [])
            }
        except Exception:
            traded_today = set()

        # Iterate over a snapshot
        for sym in list(self.watchlist_map.keys()):
            # Skip already bought symbols to prevent duplicate/re-entry trades
            if sym in self.bought_symbols or sym in traded_today:
                continue

            # Skip circuit-hit symbols
            if sym in self.circuit_set:
                continue

            # Skip already-open positions
            if sym in open_symbols:
                continue

            entry = self.watchlist_map[sym]
            strategy = entry.strategy

            # Strategy-specific time cutoffs
            if strategy == "GAP_AND_GO":
                cutoff_hour, cutoff_minute = 10, 30
            else:
                cutoff_hour, cutoff_minute = 14, 0

            entry_cutoff = current_time.replace(
                hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0
            )
            can_buy = entry_start <= current_time <= entry_cutoff

            if not can_buy:
                # We skip signal check completely if outside window
                continue
                
            # Nifty bearish filter: block long setups
            if getattr(self, "nifty_bearish", False) and strategy in ("GAP_AND_GO", "ORB_BREAKOUT", "VWAP_RECLAIM"):
                continue

            # Resolve current price
            df = candles_map.get(sym, pd.DataFrame())
            if df is None or df.empty:
                continue

            try:
                current_price = float(df["Close"].iloc[-1])
            except Exception:
                continue

            # Strategy-specific signal
            if strategy == "GAP_AND_GO":
                signal = current_price >= entry.entry_trigger
            elif strategy == "ORB_BREAKOUT":
                signal = current_price >= entry.entry_trigger
            elif strategy == "VWAP_RECLAIM":
                # H4 fix: require a genuine VWAP reclaim — price was below VWAP
                # on the previous candle and now closes above it.  A simple
                # "price > VWAP" would fire immediately at 09:30 for most stocks;
                # requiring the crossover filters out entries where price never
                # dipped below VWAP in the first place.
                df_session = df.between_time("09:15", "15:30")
                if len(df_session) >= 2:
                    vwap_series = Indicators.vwap(df_session)
                    prev_close = float(df_session["Close"].iloc[-2])
                    prev_vwap = float(vwap_series.iloc[-2])
                    curr_vwap = float(vwap_series.iloc[-1])
                    # True reclaim: was below VWAP last candle, now above
                    signal = (prev_close < prev_vwap) and (current_price > curr_vwap)
                else:
                    signal = False
            elif strategy == "GAP_FILL":
                # The validated backtest enters at the open with NO intraday
                # confirmation (entry = day open, flat 1.5% stop, target =
                # prev_close). The previous live code required price to reclaim
                # the first-15min low (current_price > low_15m) -- a gate that
                # was never in the backtest and silently skipped slow-filling
                # gap-downs that never reclaimed their own low. Removed to match
                # the validated edge: the entry window (>=09:30, <=14:00) and the
                # R:R-at-fill gate are the only filters.
                signal = True
            elif strategy == "RELATIVE_STRENGTH":
                # Dual confirmation: price must be above session VWAP AND
                # current volume ratio must show elevated participation
                # (>= 1.5x average).  This filters out low-liquidity gap drifts
                # and ensures institutional follow-through.
                df_session = df.between_time("09:15", "15:30")
                if not df_session.empty:
                    vwap_val = float(Indicators.vwap(df_session).iloc[-1])
                    vol_ratio = Indicators.volume_ratio(df_session)
                    signal = (current_price > vwap_val) and (vol_ratio >= 1.5)
                else:
                    signal = False
            else:
                signal = False

            if not signal:
                continue

            # Apply entry slippage to simulate real NSE market-order fills
            fill_price = round(current_price * (1 + SLIPPAGE_PCT), 2)

            # H3 Chase guard: only applies to price-level trigger strategies
            # (GAP_AND_GO, ORB_BREAKOUT).  VWAP_RECLAIM and GAP_FILL use dynamic
            # signal conditions — their entry_trigger is a pre-market placeholder
            # and the chase-distance concept doesn't apply.
            if strategy in ("GAP_AND_GO", "ORB_BREAKOUT"):
                if fill_price > entry.entry_trigger * 1.01:
                    logger.debug("BUY SKIPPED %s — chase guard hit (fill %.2f > trigger %.2f * 1.01)", sym, fill_price, entry.entry_trigger)
                    continue

            # Effective stop. For GAP_FILL the validated backtest sets the stop a
            # flat 1.5% below the ACTUAL entry, not below the pre-market price.
            # Anchoring to the stale watchlist stop (computed off the premarket
            # price) inflates the fill->stop distance once price ticks up and
            # crushes the R:R below the gate, starving the edge of entries.
            # Recompute from the real fill so live risk == backtested risk.
            from config import config
            if strategy == "GAP_FILL":
                effective_stop = round(fill_price * (1 - 0.015), 2)
            else:
                effective_stop = entry.stop_loss

            # Quantity sizing (uses the effective stop so risk == 1% of capital)
            if order_manager is not None:
                current_prices = {s: float(d["Close"].iloc[-1]) for s, d in candles_map.items() if d is not None and not d.empty}
                qty = order_manager.calculate_quantity(
                    fill_price, effective_stop, current_prices
                )
            else:
                qty = 1

            if qty <= 0:
                logger.debug(
                    "BUY SKIPPED %s — qty=0 (entry=%.2f sl=%.2f)",
                    sym, fill_price, effective_stop,
                )
                continue

            # Re-validate R:R with actual fill price and effective stop
            denom = fill_price - effective_stop
            if denom <= 0:
                continue
            fill_rr = (entry.target - fill_price) / denom
            if fill_rr < config.MIN_RR_RATIO:
                logger.debug("BUY SKIPPED %s — R:R at fill %.2f < %.2f", sym, fill_rr, config.MIN_RR_RATIO)
                continue

            success = portfolio.buy(
                sym,
                fill_price,
                qty,
                effective_stop,
                entry.target,
                entry.strategy,
            )

            if success:
                self.bought_symbols.add(sym)
                logger.info(
                    "BUY %s at %.2f qty=%d strategy=%s",
                    sym, fill_price, qty, strategy,
                )
                dlog.buy_decision(
                    symbol=sym,
                    strategy=strategy,
                    entry_price=fill_price,
                    stop_loss=effective_stop,
                    target=entry.target,
                    qty=qty,
                    rr_ratio=round(fill_rr, 2),
                    gap_pct=entry.gap_pct,
                    market_bias="UNKNOWN",  # bias logged separately by AgentI0
                    trigger_condition=f"price Rs{current_price:.2f} crossed entry_trigger Rs{entry.entry_trigger:.2f} (fill: {fill_price:.2f})",
                )
                notifier.send_buy(
                    sym, fill_price, qty, strategy,
                    effective_stop, entry.target,
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
        candles_map = await asyncio.to_thread(self._fetch_batch, list(self.watchlist_map.keys()))

        # Position monitoring always runs (best-effort exits for any symbol that
        # has data), even when the feed is degraded.
        self.monitor.monitor_positions(
            portfolio,
            self.watchlist_map,
            candles_map,
            current_time,
            self.circuit_set,
        )

        # Blind-feed guard: if most symbols returned no candles the live feed is
        # down -- do NOT open new positions on stale/absent data.
        feed_blind = self._check_feed_health(candles_map)

        self._evaluate_nifty_filter()
        self._maybe_apply_orb_override(candles_map, current_time, portfolio)
        if not feed_blind:
            self._check_entries(candles_map, portfolio, current_time, order_manager)

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
        # Wait for the watchlist ready event (supports both asyncio.Event and threading.Event)
        if isinstance(watchlist_ready_event, asyncio.Event):
            await watchlist_ready_event.wait()
        else:
            while not watchlist_ready_event.is_set():
                await asyncio.sleep(0.1)
        logger.info("AgentI4: watchlist ready -- starting market session loop")

        # Restore bought symbols from DB for restart resilience
        try:
            summary = portfolio.get_portfolio_summary()
            for pos in summary.get("positions", []):
                self.bought_symbols.add(pos["symbol"])
            today_report = portfolio.get_daily_report()
            for t in today_report.get("trades", []):
                self.bought_symbols.add(t["symbol"])
            if self.bought_symbols:
                logger.info("Restored bought symbols: %s", self.bought_symbols)
        except Exception as e:
            logger.error("Failed to restore bought symbols state: %s", e)

        first_cycle = True
        while True:
            # First cycle runs immediately; subsequent cycles sleep 60 s
            if first_cycle:
                first_cycle = False
            else:
                await asyncio.sleep(60)

            current_time = datetime.datetime.now(IST)
            session_end = current_time.replace(hour=15, minute=15, second=0, microsecond=0)

            if current_time >= session_end:
                break

            try:
                await self._run_cycle(portfolio, current_time, order_manager)
            except Exception as e:
                logger.error("Error in run cycle: %s", e, exc_info=True)

        # Force squareoff at end of session
        logger.info("AgentI4: market session ended -- initiating force squareoff")
        current_prices: dict[str, float] = {}
        try:
            candles_map = await asyncio.to_thread(
                self._fetch_batch, list(self.watchlist_map.keys())
            )
            for sym, df in candles_map.items():
                if df is not None and not df.empty:
                    current_prices[sym] = float(df["Close"].iloc[-1])
        except Exception as e:
            logger.error("Failed to fetch final prices for force squareoff: %s", e)

        self.force_squareoff_all(portfolio, current_prices)
