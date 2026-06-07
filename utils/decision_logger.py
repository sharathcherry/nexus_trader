"""
utils/decision_logger.py -- Structured trade decision audit log.

Writes logs/decisions/YYYY-MM-DD.log with IST timestamps.
Every entry is a human-readable block capturing the FULL reasoning
behind every decision the system makes:

  MARKET_BIAS     -- what global indices said + final bias
  SCAN_RESULT     -- gap candidates found by AgentI1
  WATCHLIST_ENTRY -- strategy assigned to each stock + why
  BUY_DECISION    -- every buy: price, qty, SL, target, trigger reason
  SELL_DECISION   -- every sell: reason, entry vs exit, P&L, hold time
  PARTIAL_EXIT    -- partial exits with rationale
  SL_UPDATE       -- trailing stop adjustments
  REVIEW_COMPLETE -- full Groq post-market review + raw AI output

Usage:
  from utils.decision_logger import dlog
  dlog.buy(symbol, price, qty, strategy, sl, target, rr, gap_pct, bias)
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

import pytz

IST = pytz.timezone("Asia/Kolkata")
_DECISION_DIR = Path("logs/decisions")
_SEP = "=" * 72


def _ist_now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def _today_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


class DecisionLogger:
    """Append-only structured decision journal, one file per trading day."""

    def __init__(self) -> None:
        _DECISION_DIR.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        return _DECISION_DIR / f"decisions_{_today_str()}.log"

    def _write(self, block: str) -> None:
        with self._log_path().open("a", encoding="utf-8") as f:
            f.write(block + "\n")

    # ------------------------------------------------------------------
    # Public log methods
    # ------------------------------------------------------------------

    def market_bias(
        self,
        bias: str,
        indices: dict[str, float],
        reasoning: str = "",
    ) -> None:
        """Log the global market bias decision made by AgentI0."""
        lines = [
            _SEP,
            f"[{_ist_now()}] MARKET_BIAS",
            f"  Bias determined : {bias}",
            "  Global indices  :",
        ]
        for name, val in indices.items():
            lines.append(f"    {name:<12} {val:>10.2f}")
        if reasoning:
            lines.append(f"  AI reasoning    : {reasoning}")
        self._write("\n".join(lines))

    def scan_result(
        self,
        candidates: list[dict],
        total_scanned: int,
        filters_applied: list[str],
    ) -> None:
        """Log AgentI1 gap scan results -- all candidates that passed filters."""
        lines = [
            _SEP,
            f"[{_ist_now()}] SCAN_RESULT",
            f"  Universe scanned  : {total_scanned} stocks",
            f"  Candidates found  : {len(candidates)}",
            f"  Filters applied   : {', '.join(filters_applied)}",
            "  Candidates        :",
        ]
        for c in candidates:
            lines.append(
                f"    {c.get('symbol','?'):<20}"
                f"  gap={c.get('gap_pct', 0):+.2f}%"
                f"  prev_vol={c.get('prev_volume', 0):>9,}"
                f"  score={c.get('gap_score', 0):.3f}"
                f"  premarket=Rs{c.get('premarket_price', 0):.2f}"
            )
        self._write("\n".join(lines))

    def watchlist_entry(
        self,
        symbol: str,
        sector: str,
        strategy: str,
        gap_pct: float,
        bias: str,
        entry_trigger: float,
        stop_loss: float,
        target: float,
        rr_ratio: float,
        atr: float,
        reasoning: str = "",
    ) -> None:
        """Log why AgentI3 assigned a strategy and set specific price levels."""
        direction = "GAP-UP" if gap_pct > 0 else "GAP-DOWN"
        lines = [
            _SEP,
            f"[{_ist_now()}] WATCHLIST_ENTRY -- {symbol}",
            f"  Sector          : {sector}",
            f"  Strategy        : {strategy}",
            f"  Decision basis  : bias={bias}, gap={gap_pct:+.2f}% ({direction})",
            f"  ATR             : Rs{atr:.2f}",
            f"  Entry trigger   : Rs{entry_trigger:.2f}",
            f"  Stop loss       : Rs{stop_loss:.2f}  (risk=Rs{entry_trigger - stop_loss:.2f})",
            f"  Target          : Rs{target:.2f}  (reward=Rs{target - entry_trigger:.2f})",
            f"  R:R ratio       : {rr_ratio:.2f}",
        ]
        if reasoning:
            lines.append(f"  Reasoning       : {reasoning}")
        self._write("\n".join(lines))

    def buy_decision(
        self,
        symbol: str,
        strategy: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        qty: int,
        rr_ratio: float,
        gap_pct: float,
        market_bias: str,
        trigger_condition: str,
    ) -> None:
        """Log the exact moment and reason a BUY was executed."""
        position_value = entry_price * qty
        risk_rs        = (entry_price - stop_loss) * qty
        reward_rs      = (target - entry_price) * qty
        lines = [
            _SEP,
            f"[{_ist_now()}] BUY_DECISION -- {symbol}",
            f"  Strategy        : {strategy}",
            f"  Trigger         : {trigger_condition}",
            f"  Entry price     : Rs{entry_price:.2f}",
            f"  Qty             : {qty} shares",
            f"  Position value  : Rs{position_value:,.2f}",
            f"  Stop loss       : Rs{stop_loss:.2f}",
            f"  Target          : Rs{target:.2f}",
            f"  R:R ratio       : {rr_ratio:.2f}",
            f"  Max risk        : Rs{risk_rs:.2f}",
            f"  Max reward      : Rs{reward_rs:.2f}",
            f"  Gap context     : {gap_pct:+.2f}%",
            f"  Market bias     : {market_bias}",
        ]
        self._write("\n".join(lines))

    def sell_decision(
        self,
        symbol: str,
        exit_reason: str,
        entry_price: float,
        exit_price: float,
        qty: int,
        gross_pnl: float,
        net_pnl: float,
        brokerage: float,
        entry_time: str,
        strategy: str,
    ) -> None:
        """Log every sell with full P&L breakdown and hold time."""
        direction = "PROFIT" if net_pnl >= 0 else "LOSS"
        try:
            entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
            hold_mins = int(
                (datetime.now(IST) - entry_dt.astimezone(IST)).total_seconds() / 60
            )
            hold_str = f"{hold_mins} min"
        except Exception:
            hold_str = "unknown"

        lines = [
            _SEP,
            f"[{_ist_now()}] SELL_DECISION -- {symbol}  [{direction}]",
            f"  Exit reason     : {exit_reason}",
            f"  Strategy        : {strategy}",
            f"  Entry price     : Rs{entry_price:.2f}",
            f"  Exit price      : Rs{exit_price:.2f}",
            f"  Move            : {((exit_price - entry_price) / entry_price * 100):+.2f}%",
            f"  Qty             : {qty} shares",
            f"  Gross P&L       : Rs{gross_pnl:+.2f}",
            f"  Brokerage       : Rs{brokerage:.2f}",
            f"  Net P&L         : Rs{net_pnl:+.2f}",
            f"  Hold time       : {hold_str}",
        ]
        self._write("\n".join(lines))

    def partial_exit(
        self,
        symbol: str,
        exit_price: float,
        exit_qty: int,
        remaining_qty: int,
        pnl: float,
        reason: str,
    ) -> None:
        """Log partial exits (1:1 R:R lock-in)."""
        lines = [
            _SEP,
            f"[{_ist_now()}] PARTIAL_EXIT -- {symbol}",
            f"  Exit price      : Rs{exit_price:.2f}",
            f"  Qty exited      : {exit_qty} shares",
            f"  Qty remaining   : {remaining_qty} shares",
            f"  P&L on exit     : Rs{pnl:+.2f}",
            f"  Reason          : {reason}",
        ]
        self._write("\n".join(lines))

    def sl_update(
        self,
        symbol: str,
        strategy: str,
        old_sl: float,
        new_sl: float,
        current_price: float,
        reason: str,
    ) -> None:
        """Log every trailing stop update."""
        lines = [
            _SEP,
            f"[{_ist_now()}] SL_UPDATE -- {symbol}",
            f"  Strategy        : {strategy}",
            f"  Current price   : Rs{current_price:.2f}",
            f"  Old stop loss   : Rs{old_sl:.2f}",
            f"  New stop loss   : Rs{new_sl:.2f}  (+Rs{new_sl - old_sl:.2f})",
            f"  Reason          : {reason}",
        ]
        self._write("\n".join(lines))

    def review_complete(
        self,
        verdict: str,
        summary: str,
        winning_strategies: list[str],
        underperforming_strategies: list[str],
        parameter_adjustments: list[dict],
        tomorrow_watch: list[str],
        raw_ai_response: str,
        model_used: str,
        tokens_used: int,
    ) -> None:
        """Log the full post-market review including raw AI output."""
        lines = [
            _SEP,
            f"[{_ist_now()}] REVIEW_COMPLETE",
            f"  Model           : {model_used}",
            f"  Tokens used     : {tokens_used}",
            f"  Verdict         : {verdict}",
            f"  Winning strats  : {', '.join(winning_strategies) or 'none'}",
            f"  Underperforming : {', '.join(underperforming_strategies) or 'none'}",
            f"  Tomorrow watch  : {', '.join(tomorrow_watch) or 'none'}",
            "",
            "  SUMMARY:",
        ]
        for line in textwrap.wrap(summary, width=68):
            lines.append(f"    {line}")

        if parameter_adjustments:
            lines.append("")
            lines.append("  PARAMETER ADJUSTMENTS:")
            for adj in parameter_adjustments:
                lines.append(
                    f"    {adj.get('param_name','?'):<25}"
                    f"  {adj.get('current_value','?')} -> {adj.get('suggested_value','?')}"
                    f"  ({adj.get('reason','')[:50]})"
                )

        lines.append("")
        lines.append("  RAW AI OUTPUT:")
        lines.append("  " + "-" * 68)
        for ln in raw_ai_response.splitlines():
            lines.append(f"  {ln}")
        lines.append("  " + "-" * 68)

        self._write("\n".join(lines))

    def session_start(self) -> None:
        self._write(
            f"\n{'#' * 72}\n"
            f"# SESSION START  {_ist_now()}\n"
            f"{'#' * 72}"
        )

    def session_end(self, total_trades: int, daily_pnl: float) -> None:
        direction = "PROFIT" if daily_pnl >= 0 else "LOSS"
        self._write(
            f"\n{'#' * 72}\n"
            f"# SESSION END    {_ist_now()}\n"
            f"# Total trades   {total_trades}\n"
            f"# Daily P&L      Rs{daily_pnl:+.2f}  [{direction}]\n"
            f"{'#' * 72}\n"
        )


# Module-level singleton
dlog = DecisionLogger()
