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

    def calculate_quantity(self, entry_price: float, stop_loss: float, current_prices: dict[str, float] | None = None) -> int:
        """
        Size position by 1% risk per trade, capped at MAX_POSITION_PCT of capital.

        With MAX_POSITION_PCT=20% and MAX_OPEN_POSITIONS=5, the system can
        deploy the full Rs1,00,000 capital across 5 positions (Rs20,000 each).

        Args:
            entry_price: Proposed entry price.
            stop_loss:   Initial stop loss price.
            current_prices: Optional map of symbol -> live price to calculate total equity.

        Returns:
            Integer share quantity (0 if risk_per_share <= 0).
        """
        total_equity = self.portfolio.capital
        if current_prices:
            for pos in self.portfolio._get_open_positions():
                sym = pos["symbol"]
                price = current_prices.get(sym, pos["entry_price"])
                total_equity += pos["qty"] * price

        risk_amount = total_equity * config.RISK_PER_TRADE_PCT
        risk_per_share = abs(entry_price - stop_loss)

        if risk_per_share <= 0:
            return 0

        qty = int(risk_amount / risk_per_share)
        max_qty = int((total_equity * config.MAX_POSITION_PCT) / entry_price)
        return min(qty, max_qty)

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
