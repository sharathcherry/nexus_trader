"""
execution/order_manager.py — OrderManager

Stateless order execution layer that wraps PaperPortfolio.
Handles:
  - Quantity sizing by 1% risk per trade (PORT-11)
  - Exit checks: target, stop loss, partial exit at 1:1 R:R (PORT-12)
  - Force squareoff gate at 15:15 IST (STATE.md — dual safety)
  - Trailing stop updates: GAP_AND_GO (0.75 ATR) and ORB_BREAKOUT (breakeven) (PORT-13)
  - Circuit breaker detection: price unchanged for 3+ consecutive cycles

Coupling pattern (D-10, D-11):
  OrderManager.__init__(portfolio: PaperPortfolio)
  All portfolio mutations go through self.portfolio.* — no direct DB access here.
"""

from datetime import datetime

import pytz

from config import config
from execution.portfolio import PaperPortfolio
from utils.logger import setup_logger

logger = setup_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Simulated slippage on entry: 0.15% above requested price.
# Mirrors real-world market order fill on NSE (spread + impact cost).
_SLIPPAGE_PCT = 0.0015


class OrderManager:
    """
    Stateless order execution layer over PaperPortfolio.

    All persistence is delegated to self.portfolio.
    Tracks price history for circuit breaker detection (in-memory only).
    """

    def __init__(self, portfolio: PaperPortfolio) -> None:
        self.portfolio = portfolio
        # {symbol: [price1, price2, price3]} — last 3 prices per symbol
        self._price_history: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # Quantity sizing (PORT-11)
    # ------------------------------------------------------------------

    def calculate_quantity(self, entry_price: float, stop_loss: float) -> int:
        """
        Size position by 1% risk per trade, capped at MAX_POSITION_PCT of capital.

        With MAX_POSITION_PCT=20% and MAX_OPEN_POSITIONS=5, the system can
        deploy the full Rs1,00,000 capital across 5 positions (Rs20,000 each).

        Args:
            entry_price: Proposed entry price.
            stop_loss:   Initial stop loss price.

        Returns:
            Integer share quantity (0 if risk_per_share <= 0).
        """
        current_capital = self.portfolio.capital
        risk_amount = current_capital * config.RISK_PER_TRADE_PCT  # e.g. ₹1,000
        risk_per_share = abs(entry_price - stop_loss)

        if risk_per_share <= 0:
            return 0

        qty = int(risk_amount / risk_per_share)
        max_qty = int((current_capital * config.MAX_POSITION_PCT) / entry_price)  # Rs20,000 cap per position
        return min(qty, max_qty)

    # ------------------------------------------------------------------
    # Exit checks (PORT-12)
    # ------------------------------------------------------------------

    def check_and_execute_exits(self, live_prices: dict[str, float]) -> None:
        """
        Evaluate all open positions against live prices and execute exits.

        Called every polling cycle (60 s) during market session.

        Exit logic per position:
          1. Force squareoff gate: if >= 15:15 IST → close all and return
          2. Target hit → sell at target
          3. Stop loss hit → sell at stop loss
          4. 1:1 R:R reached and not yet partially exited → partial exit (50%)

        Circuit breaker: logs WARNING if price unchanged for 3 consecutive cycles.

        Never raises — all errors caught and logged.
        """
        try:
            now = datetime.now(IST)

            # 1. Force squareoff gate (STATE.md dual safety)
            if now.hour > 15 or (now.hour == 15 and now.minute >= 15):
                logger.info(
                    "15:15 gate triggered — calling force_squareoff_all()"
                )
                self.portfolio.force_squareoff_all(live_prices)
                return

            positions = self.portfolio._get_open_positions()

            for position in positions:
                symbol = position["symbol"]

                if symbol not in live_prices:
                    logger.debug("No live price for %s — skipping exit check", symbol)
                    continue

                current_price = live_prices[symbol]

                # Circuit breaker tracking
                self._update_price_history(symbol, current_price)

                # 2. Target hit
                if current_price >= position["target"]:
                    logger.info(
                        "TARGET HIT %s @ Rs%.2f (target=Rs%.2f)",
                        symbol, current_price, position["target"],
                    )
                    self.portfolio.sell(
                        symbol, current_price, position["qty"], "TARGET"
                    )
                    continue

                # 3. Stop loss hit
                if current_price <= position["stop_loss"]:
                    logger.info(
                        "STOP LOSS HIT %s @ Rs%.2f (SL=Rs%.2f)",
                        symbol, current_price, position["stop_loss"],
                    )
                    self.portfolio.sell(
                        symbol, current_price, position["qty"], "STOP_LOSS"
                    )
                    continue

                # 4. Partial exit at 1:1 R:R (if not already partially exited)
                if not position["partial_exited"]:
                    risk = position["entry_price"] - position["stop_loss"]
                    half_way = position["entry_price"] + risk  # True 1:1 R:R point
                    if current_price >= half_way:
                        exit_qty = position["qty"] // 2
                        if exit_qty > 0:
                            self.portfolio.partial_exit(
                                symbol, current_price, exit_qty, "PARTIAL_EXIT"
                            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "check_and_execute_exits error: %s", exc, exc_info=True
            )

    def _update_price_history(self, symbol: str, price: float) -> None:
        """Track last 3 prices; log WARNING if unchanged for 3 consecutive cycles."""
        history = self._price_history.get(symbol, [])
        history.append(price)
        if len(history) > 3:
            history = history[-3:]
        self._price_history[symbol] = history

        if len(history) == 3 and len(set(history)) == 1:
            logger.warning(
                "POSSIBLE_CIRCUIT %s — price unchanged 3 cycles (Rs%.2f)",
                symbol, price,
            )

    # ------------------------------------------------------------------
    # Trailing stops (PORT-13)
    # ------------------------------------------------------------------

    def update_trailing_stops(
        self, live_prices: dict[str, float], atrs: dict[str, float]
    ) -> None:
        """
        Update trailing stop losses for open positions.

        Called every polling cycle after check_and_execute_exits().

        GAP_AND_GO: trail at 0.75 ATR below current price once 1 ATR in profit.
        ORB_BREAKOUT: move SL to entry_price (breakeven) at 1:1 R:R.
        Other strategies: no trailing stop applied.

        Never raises — missing ATR values handled gracefully.
        """
        try:
            positions = self.portfolio._get_open_positions()

            for position in positions:
                symbol = position["symbol"]

                if symbol not in live_prices:
                    continue

                current_price = live_prices[symbol]
                strategy = position["strategy"]

                if strategy == "GAP_AND_GO":
                    self._trail_gap_and_go(position, symbol, current_price, atrs)

                elif strategy == "ORB_BREAKOUT":
                    self._trail_orb_breakout(position, symbol, current_price)

                # GAP_FILL, VWAP_RECLAIM: no trailing stop

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "update_trailing_stops error: %s", exc, exc_info=True
            )

    def _trail_gap_and_go(
        self,
        position,
        symbol: str,
        current_price: float,
        atrs: dict[str, float],
    ) -> None:
        """
        GAP_AND_GO trailing: trail at 0.75 ATR below current price
        once the position is at least 1 ATR in profit.
        """
        if symbol not in atrs:
            return

        atr = atrs[symbol]
        if atr <= 0:
            return

        entry_price = position["entry_price"]

        if current_price >= entry_price + atr:  # 1 ATR in profit
            new_sl = current_price - (0.75 * atr)
            if new_sl > position["stop_loss"]:
                self.portfolio.update_stop_loss(symbol, new_sl)

    def _trail_orb_breakout(
        self,
        position,
        symbol: str,
        current_price: float,
    ) -> None:
        """
        ORB_BREAKOUT: move SL to breakeven (entry_price) when 1:1 R:R is reached.
        No further action once SL already equals entry_price.
        """
        entry_price = position["entry_price"]
        risk = entry_price - position["stop_loss"]

        if current_price >= entry_price + risk:  # 1:1 R:R reached
            if entry_price > position["stop_loss"]:  # not yet at breakeven
                self.portfolio.update_stop_loss(symbol, entry_price)
