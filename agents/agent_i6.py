"""
agents/agent_i6.py — AgentI6: Stateful position monitor.

Called by AgentI4 each polling cycle to:
  - Detect circuit-breaker conditions (price frozen 3+ cycles)
  - Execute hard exits (SL hit, target hit)
  - Execute partial exits at 1R profit (GAP_AND_GO, ORB_BREAKOUT only)
  - Apply trailing stop logic per strategy

Partial exit and trailing SL are strategy-specific:
  GAP_AND_GO   — partial exit + ATR-based trailing SL
  ORB_BREAKOUT — partial exit + breakeven trailing SL
  GAP_FILL     — fixed SL, no partial exit, no trailing SL
  VWAP_RECLAIM — fixed SL, no partial exit, no trailing SL
"""

from __future__ import annotations

import datetime
import pandas as pd
from collections import deque

from config import config
from utils.logger import setup_logger
from utils.telegram import notifier
from utils.decision_logger import dlog

logger = setup_logger(__name__)


class AgentI6:
    """
    Stateful position monitor for the nexus_trader intraday loop.

    Maintains per-symbol price history deques for circuit detection.
    All portfolio mutations go through the passed PaperPortfolio instance.
    """

    def __init__(self) -> None:
        # deque(maxlen=3) per symbol — tracks last 3 prices for circuit detection
        self._price_history: dict[str, deque] = {}

    # ------------------------------------------------------------------
    # Circuit detection
    # ------------------------------------------------------------------

    def _check_circuit(
        self,
        symbol: str,
        current_price: float,
        circuit_set: set,
    ) -> bool:
        """
        Append current_price to the symbol's deque (maxlen=3).

        Returns True (and adds to circuit_set) if all 3 values are identical,
        indicating a possible circuit-limit halt.
        Returns False otherwise.
        """
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=3)

        d = self._price_history[symbol]
        d.append(current_price)

        if len(d) == 3 and len(set(d)) == 1:
            logger.warning("POSSIBLE_CIRCUIT detected for %s", symbol)
            circuit_set.add(symbol)
            notifier.send_circuit_breaker(symbol, current_price)
            return True

        return False

    # ------------------------------------------------------------------
    # Main monitoring loop
    # ------------------------------------------------------------------

    def monitor_positions(
        self,
        portfolio,
        watchlist_map: dict,
        current_prices: dict,
        current_time: datetime.datetime,
        circuit_set: set,
    ) -> list[str]:
        """
        Iterate over all open positions and apply exit/trail logic.

        Args:
            portfolio:      PaperPortfolio instance.
            watchlist_map:  dict[str, WatchlistEntry] — keyed by symbol.
            current_prices: dict[str, pd.DataFrame] — keyed by symbol, OHLCV df.
            current_time:   IST-aware datetime.
            circuit_set:    Shared set[str]; symbols in circuit are skipped.

        Returns:
            List of action strings describing actions taken (for caller logging).
        """
        actions: list[str] = []
        summary = portfolio.get_portfolio_summary()

        for pos in summary.get("positions", []):
            sym = pos["symbol"]

            # --- Resolve current price from OHLCV DataFrame ---
            try:
                df = current_prices.get(sym, pd.DataFrame())
                if df is None or df.empty:
                    continue
                current_price = float(df["Close"].iloc[-1])
            except Exception as exc:
                logger.warning(
                    "Bad candle data for %s — skipping: %s", sym, exc
                )
                continue

            # --- Skip symbols already in circuit ---
            if sym in circuit_set:
                continue

            # --- Circuit detection ---
            if self._check_circuit(sym, current_price, circuit_set):
                continue

            # --- Hard exit: stop loss ---
            if current_price <= pos["stop_loss"]:
                portfolio.sell(sym, current_price, pos["qty"], "SL_HIT")
                actions.append(f"SL_HIT:{sym}@{current_price:.2f}")
                dlog.sell_decision(
                    symbol=sym, exit_reason="SL_HIT",
                    entry_price=pos["entry_price"], exit_price=current_price,
                    qty=pos["qty"],
                    gross_pnl=(current_price - pos["entry_price"]) * pos["qty"],
                    net_pnl=(current_price - pos["entry_price"]) * pos["qty"],  # approx
                    brokerage=0.0,
                    entry_time=pos.get("entry_time", ""),
                    strategy=pos.get("strategy", ""),
                )
                notifier.send_sell(sym, current_price, pos["qty"], "SL_HIT")
                continue

            # --- Hard exit: target ---
            if current_price >= pos["target"]:
                portfolio.sell(sym, current_price, pos["qty"], "TARGET_HIT")
                actions.append(f"TARGET_HIT:{sym}@{current_price:.2f}")
                dlog.sell_decision(
                    symbol=sym, exit_reason="TARGET_HIT",
                    entry_price=pos["entry_price"], exit_price=current_price,
                    qty=pos["qty"],
                    gross_pnl=(current_price - pos["entry_price"]) * pos["qty"],
                    net_pnl=(current_price - pos["entry_price"]) * pos["qty"],  # approx
                    brokerage=0.0,
                    entry_time=pos.get("entry_time", ""),
                    strategy=pos.get("strategy", ""),
                )
                notifier.send_sell(sym, current_price, pos["qty"], "TARGET_HIT")
                continue

            strategy = pos["strategy"]

            # --- Partial exit ---
            # Only for GAP_AND_GO and ORB_BREAKOUT; not for GAP_FILL / VWAP_RECLAIM
            if strategy in ("GAP_AND_GO", "ORB_BREAKOUT"):
                watchlist_entry = watchlist_map.get(sym)
                if watchlist_entry is not None:
                    # Use original SL from watchlist (not the potentially trailed pos SL)
                    original_sl = watchlist_entry.stop_loss
                    risk = pos["entry_price"] - original_sl
                    partial_exit_threshold = pos["entry_price"] + risk

                    if not pos["partial_exited"] and current_price >= partial_exit_threshold:
                        exit_qty = pos["qty"] // 2
                        if exit_qty > 0:
                            portfolio.partial_exit(
                                sym, current_price, exit_qty, "PARTIAL_EXIT"
                            )
                            actions.append(
                                f"PARTIAL_EXIT:{sym}@{current_price:.2f} qty={exit_qty}"
                            )
                            dlog.partial_exit(
                                symbol=sym, exit_price=current_price,
                                exit_qty=exit_qty,
                                remaining_qty=pos["qty"] - exit_qty,
                                pnl=(current_price - pos["entry_price"]) * exit_qty,
                                reason="1:1 R:R lock-in reached",
                            )
                            notifier.send_partial_exit(sym, current_price, exit_qty)

            # --- Trailing SL & Breakeven SL ---
            # Re-fetch pos to get updated partial_exited flag after potential partial exit
            _pos_row = portfolio._get_position(sym)
            if _pos_row is None:
                # Position was fully closed upstream (race); nothing left to trail
                continue
            _pos = dict(_pos_row)

            watchlist_entry = watchlist_map.get(sym)
            if watchlist_entry is None:
                logger.warning(
                    "No watchlist entry for %s — skipping trailing SL", sym
                )
                continue

            # Both GAP_AND_GO and ORB_BREAKOUT move SL to breakeven on partial exit
            if strategy in ("GAP_AND_GO", "ORB_BREAKOUT"):
                if _pos["partial_exited"] and pos["entry_price"] > _pos["stop_loss"]:
                    dlog.sl_update(
                        symbol=sym, strategy=strategy,
                        old_sl=_pos["stop_loss"], new_sl=pos["entry_price"],
                        current_price=current_price,
                        reason="partial exit done; moved SL to breakeven (entry price)",
                    )
                    portfolio.update_stop_loss(sym, pos["entry_price"])
                    _pos["stop_loss"] = pos["entry_price"]
                    actions.append(
                        f"BREAKEVEN_SL:{sym}@{pos['entry_price']:.2f}"
                    )

            # GAP_AND_GO additional ATR-based trailing SL
            if strategy == "GAP_AND_GO":
                atr = watchlist_entry.atr
                if atr and atr > 0:
                    if current_price >= pos["entry_price"] + atr:
                        new_sl = current_price - 0.75 * atr
                        if new_sl > _pos["stop_loss"]:
                            dlog.sl_update(
                                symbol=sym, strategy="GAP_AND_GO",
                                old_sl=_pos["stop_loss"], new_sl=new_sl,
                                current_price=current_price,
                                reason=f"price Rs{current_price:.2f} >= entry+ATR Rs{pos['entry_price']+atr:.2f}; trail at 0.75xATR",
                            )
                            portfolio.update_stop_loss(sym, new_sl)
                            actions.append(
                                f"TRAIL_SL:{sym} new_sl={new_sl:.2f}"
                            )

            # GAP_FILL and VWAP_RECLAIM: fixed SL, no trailing

        return actions
