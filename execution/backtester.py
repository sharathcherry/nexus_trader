from __future__ import annotations
import math
import time
from datetime import date, datetime, timedelta
from collections import defaultdict
from typing import Any

import yfinance as yf

from config import config
from data.universe import get_nse_universe
from utils.logger import setup_logger

logger = setup_logger(__name__)


class NexusBacktester:
    """Rule-based daily OHLC backtest engine. No AI agents, no API calls."""

    def __init__(self, start_date: str, end_date: str, capital: float | None = None) -> None:
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        self.end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        self.capital = capital if capital is not None else config.CAPITAL
        logger.info(f"NexusBacktester: {start_date} → {end_date}, capital=₹{self.capital:,.0f}")

    def _fetch_day_data(self, symbols: list[str], trade_date: date) -> dict[str, dict]:
        """Fetch OHLCV for all symbols in batches of 20. Returns per-symbol dicts."""
        result: dict[str, dict] = {}
        batch_size = 20

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            try:
                raw = yf.download(
                    tickers=batch,
                    period="5d",
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                )
                time.sleep(0.2)  # rate-limit guard after every batch

                if raw.empty:
                    logger.warning(f"Batch returned empty DataFrame for {batch[:3]}...")
                    continue

                for sym in batch:
                    try:
                        # Single-ticker: flat Index; multi-ticker: MultiIndex
                        if len(batch) == 1:
                            sym_df = raw
                        else:
                            sym_df = raw.xs(sym, axis=1, level=1)

                        if sym_df.empty:
                            continue

                        # Strip timezone so date comparisons work
                        sym_df.index = (
                            sym_df.index.tz_localize(None)
                            if hasattr(sym_df.index, "tz_localize") and sym_df.index.tz
                            else sym_df.index
                        )
                        target_rows = [r for r in sym_df.index if r.date() == trade_date]
                        prev_rows = [r for r in sym_df.index if r.date() < trade_date]

                        if not target_rows or not prev_rows:
                            continue

                        today_row = sym_df.loc[target_rows[-1]]
                        prev_row = sym_df.loc[prev_rows[-1]]

                        result[sym] = {
                            "prev_close": float(prev_row["Close"]),
                            "prev_volume": float(prev_row["Volume"]),
                            "open": float(today_row["Open"]),
                            "high": float(today_row["High"]),
                            "low": float(today_row["Low"]),
                            "close": float(today_row["Close"]),
                        }
                    except Exception as e:
                        logger.debug(f"{sym}: skipped ({e})")
                        continue
            except Exception as e:
                logger.warning(f"Batch fetch failed for {batch[:3]}: {e}")
                time.sleep(0.2)
                continue

        return result

    def _calculate_brokerage(self, buy_price: float, sell_price: float, qty: int) -> dict:
        from utils.brokerage import calculate_brokerage
        return calculate_brokerage(buy_price, sell_price, qty)

    def _simulate_day(
        self, trade_date: date, running_capital: float, equity_curve: list[float]
    ) -> tuple[list[dict], float]:
        """Simulate one trading day. Returns (trades, updated_capital)."""
        try:
            universe = get_nse_universe()
            symbols = [s["symbol"] for s in universe]

            day_data = self._fetch_day_data(symbols, trade_date)

            if not day_data:
                equity_curve.append(running_capital)
                return [], running_capital

            # Gap filter and candidate scoring
            candidates = []
            for sym, d in day_data.items():
                if d["prev_close"] <= 0:
                    continue
                gap_pct = (d["open"] - d["prev_close"]) / d["prev_close"] * 100

                # Apply filters
                if not (config.GAP_MIN_PCT <= abs(gap_pct) <= config.GAP_MAX_PCT):
                    continue
                if d["prev_volume"] < config.MIN_PREV_VOLUME:
                    continue
                if not (config.MIN_PRICE <= d["open"] <= config.MAX_PRICE):
                    continue

                gap_score = abs(gap_pct) * min(d["prev_volume"] / 500_000, 3.0)
                candidates.append((gap_score, sym, d, gap_pct))

            # Sort by gap_score descending, take top MAX_OPEN_POSITIONS
            candidates.sort(key=lambda x: x[0], reverse=True)
            candidates = candidates[:config.MAX_OPEN_POSITIONS]

            daily_pnl = 0.0
            trades = []

            for gap_score, sym, d, gap_pct in candidates:
                entry = d["open"]
                target = entry * (1 + config.MIN_RR_RATIO * config.RISK_PER_TRADE_PCT)
                stop = entry * (1 - config.RISK_PER_TRADE_PCT)

                # Position sizing
                risk_amount = running_capital * config.RISK_PER_TRADE_PCT
                risk_per_share = entry - stop
                if risk_per_share <= 0:
                    continue
                
                qty = max(1, int(risk_amount / risk_per_share))
                max_qty = int((running_capital * config.MAX_POSITION_PCT) / entry)
                qty = min(qty, max_qty) if max_qty > 0 else qty

                # Exit logic: STOP_HIT wins if both hit same day (conservative backtesting)
                if d["high"] >= target and d["low"] <= stop:
                    exit_price = stop
                    exit_reason = "STOP_HIT"
                elif d["high"] >= target:
                    exit_price = target
                    exit_reason = "TARGET_HIT"
                elif d["low"] <= stop:
                    exit_price = stop
                    exit_reason = "STOP_HIT"
                else:
                    exit_price = d["close"]
                    exit_reason = "EOD"

                gross_pnl = (exit_price - entry) * qty
                charges = self._calculate_brokerage(entry, exit_price, qty)
                net_pnl = gross_pnl - charges["total_charges"]

                daily_pnl += net_pnl

                trades.append({
                    "symbol": sym,
                    "date": trade_date.isoformat(),
                    "entry": entry,
                    "exit": exit_price,
                    "qty": qty,
                    "gap_pct": gap_pct,
                    "exit_reason": exit_reason,
                    "gross_pnl": gross_pnl,
                    "charges": charges["total_charges"],
                    "net_pnl": net_pnl,
                })

                # Daily loss limit check
                if daily_pnl < -(config.DAILY_LOSS_LIMIT_PCT * running_capital):
                    logger.warning(f"Daily loss limit hit on {trade_date} — stopping for the day")
                    break

            running_capital += daily_pnl
            equity_curve.append(running_capital)
            return trades, running_capital

        except Exception as e:
            logger.error(f"_simulate_day({trade_date}) failed: {e}", exc_info=True)
            equity_curve.append(running_capital)
            return [], running_capital

    def _compute_metrics(
        self, trades: list[dict], equity_curve: list[float], trading_days_processed: int
    ) -> dict:
        """Compute the 8 required performance metrics + trading_days_processed bonus."""
        total_trades = len(trades)

        win_rate = 0.0
        if total_trades > 0:
            wins = sum(1 for t in trades if t["net_pnl"] > 0)
            win_rate = wins / total_trades

        total_net_pnl = sum(t["net_pnl"] for t in trades)
        total_return_pct = total_net_pnl / self.capital if self.capital > 0 else 0.0

        # Sharpe ratio (annualized, population std)
        sharpe_ratio = 0.0
        if len(equity_curve) > 1:
            daily_returns = [
                (equity_curve[i + 1] - equity_curve[i]) / self.capital
                for i in range(len(equity_curve) - 1)
            ]
            mean_r = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            std_r = math.sqrt(variance)
            if std_r > 0:
                sharpe_ratio = (mean_r / std_r) * math.sqrt(252)

        # Max drawdown
        max_drawdown_pct = 0.0
        if equity_curve:
            peak = equity_curve[0]
            for val in equity_curve:
                if val > peak:
                    peak = val
                dd = (peak - val) / peak if peak > 0 else 0.0
                if dd > max_drawdown_pct:
                    max_drawdown_pct = dd

        # Profit factor
        gross_wins = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        gross_losses = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
        if gross_losses == 0:
            profit_factor = float("inf") if gross_wins > 0 else 0.0
        else:
            profit_factor = gross_wins / gross_losses

        # Monthly returns
        monthly: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
        for t in trades:
            month_key = t["date"][:7]  # "YYYY-MM"
            monthly[month_key]["pnl"] += t["net_pnl"]
            monthly[month_key]["trades"] += 1
        monthly_returns = [
            {"month": k, "pnl": v["pnl"], "trades": v["trades"]}
            for k, v in sorted(monthly.items())
        ]

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_net_pnl": total_net_pnl,
            "total_return_pct": total_return_pct,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "profit_factor": profit_factor,
            "monthly_returns": monthly_returns,
            "trading_days_processed": trading_days_processed,  # bonus key
        }

    def run(self) -> dict:
        """Run the full backtest. Returns 8-key metrics dict."""
        all_trades: list[dict] = []
        equity_curve: list[float] = [self.capital]
        running_capital = self.capital
        trading_days_processed = 0

        current_date = self.start_date
        while current_date <= self.end_date:
            if config.is_trading_day(current_date):
                day_trades, running_capital = self._simulate_day(
                    current_date, running_capital, equity_curve
                )
                all_trades.extend(day_trades)
                trading_days_processed += 1
                logger.info(
                    f"{current_date}: {len(day_trades)} trades, "
                    f"equity=₹{running_capital:,.0f}"
                )
            current_date += timedelta(days=1)

        logger.info(f"Backtest complete: {trading_days_processed} days, {len(all_trades)} trades")
        return self._compute_metrics(all_trades, equity_curve, trading_days_processed)
