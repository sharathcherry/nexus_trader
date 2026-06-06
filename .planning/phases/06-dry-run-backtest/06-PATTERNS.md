# Phase 6: Dry-Run & Backtest - Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 4 (3 new files + 1 modified file)
**Analogs found:** 4 / 4 (all files have analogs in existing source or verified plan files)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `main.py` | entry-point | request-response (CLI branch) | `main.py` current stub + `05-PATTERNS.md` §"main.py" | exact (same file — additive change to parse_args + main branch) |
| `backtest.py` | entry-point | request-response (CLI → batch) | `main.py` + `05-PATTERNS.md` §"parse_args pattern" | role-match (same argparse/banner/entry pattern) |
| `execution/backtester.py` | service | batch (CRUD + transform) | `config.py` class pattern + `03-CONTEXT.md` brokerage math + `02-PATTERNS.md` yfinance batch fetch | role-match (no batch service exists yet; draws from data-layer and portfolio-engine patterns) |
| `README.md` | documentation | static | none | no analog (first README in project) |

---

## Pattern Assignments

### `main.py` (entry-point, request-response — modified)

**Analog:** Phase 5 `05-PATTERNS.md` §"main.py" (complete implementation spec) + `05-02-PLAN.md` Task 3 (full implementation instructions)

**Current stub** (`main.py` lines 1–13 — existing source):
```python
from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    logger.info("nexus_trader starting up (placeholder — Phase 5 adds full orchestrator)")
    logger.info(f"Capital: ₹{config.CAPITAL:,}")


if __name__ == "__main__":
    main()
```

Phase 6 change: The Phase 5 `main.py` rewrite (already planned) has `parse_args()` returning a Namespace with only `--dry-run`. Phase 6 changes the `--dry-run` branch semantics inside `main()` — the argparse setup is NOT changed.

**Phase 5 parse_args pattern** (from `05-PATTERNS.md` lines 264–278 — copy verbatim):
```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='nexus_trader — NSE intraday paper trading pipeline'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Run pipeline without placing any orders (agents execute, orders skipped)'
    )
    return parser.parse_args()
```

**Phase 6 modification to `main()` — dry-run branch** (per CONTEXT.md D-03):

Replace the `trader = NexusTrader(dry_run=args.dry_run)` + `TradingScheduler` block with a branch:

```python
def main() -> None:
    # ... sys.stdout.reconfigure, parse_args, print_banner unchanged ...
    args = parse_args()
    print_banner(dry_run=args.dry_run)

    if args.dry_run:
        # Phase 6 one-shot mode: run pre-market pipeline on yesterday's data, then exit
        from datetime import timedelta
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        trader = NexusTrader(dry_run=False)  # live agents, no order skipping
        trader.run_pre_market_pipeline()     # runs on yesterday's date (see D-02)
        sys.exit(0)

    # Normal live path — TradingScheduler started only if NOT dry-run
    trader = NexusTrader(dry_run=False)
    scheduler = TradingScheduler(nexus_trader=trader)
    scheduler.start()
    logger.info('nexus_trader running — press Ctrl+C to stop')
    try:
        shutdown_event.wait()
    except KeyboardInterrupt:
        print('\nCtrl+C — shutting down...')
        trader.portfolio.force_squareoff_all()
        trader.portfolio.save_state()
        scheduler.shutdown()
        sys.exit(0)
```

Key contracts from CONTEXT.md D-01/D-02/D-03:
- `TradingScheduler` is NEVER started in dry-run mode
- `NexusTrader(dry_run=False)` — dry_run parameter is repurposed; constructor always gets False
- `print_banner(dry_run=True)` still shows "DRY-RUN" in the info block (no banner change)
- `run_pre_market_pipeline()` must use yesterday's date: the method internally calls `datetime.now(ist).date()` — for dry-run, override requires patching or the method must accept a `date_override` parameter. Planner must decide implementation strategy for the date override.

**Imports pattern for `main.py`** (from `05-PATTERNS.md` lines 243–253 — existing Phase 5 imports, no new imports for Phase 6):
```python
from __future__ import annotations

import argparse
import sys
import threading

from config import config
from execution.scheduler import NexusTrader, TradingScheduler
from utils.logger import setup_logger

logger = setup_logger(__name__)
shutdown_event = threading.Event()
```

---

### `backtest.py` (entry-point, request-response)

**Analog:** `main.py` Phase 5 pattern (argparse + banner + entry guard) from `05-PATTERNS.md`

**Imports pattern** (modeled on `05-PATTERNS.md` §"Imports pattern for main.py" — adapted for backtest):
```python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from config import config
from execution.backtester import NexusBacktester
from utils.logger import setup_logger

logger = setup_logger(__name__)
```

Key differences from `main.py`:
- No `threading`, no `shutdown_event` — batch mode, no blocking loop
- No `NexusTrader`, `TradingScheduler` — never imported in `backtest.py`
- `NexusBacktester` is the only execution import (per CONTEXT.md D-17)

**argparse pattern** (per CONTEXT.md D-16 — modeled on `05-PATTERNS.md` parse_args):
```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='nexus_trader — NSE intraday paper trading backtester'
    )
    parser.add_argument(
        '--start',
        required=True,
        metavar='YYYY-MM-DD',
        help='Backtest start date (inclusive)'
    )
    parser.add_argument(
        '--end',
        required=True,
        metavar='YYYY-MM-DD',
        help='Backtest end date (inclusive)'
    )
    parser.add_argument(
        '--capital',
        type=float,
        default=None,
        help=f'Starting capital in INR (default: config.CAPITAL = {config.CAPITAL:,})'
    )
    return parser.parse_args()
```

Date validation pattern (per CONTEXT.md D-16):
```python
def validate_dates(start_str: str, end_str: str) -> tuple[datetime, datetime]:
    fmt = '%Y-%m-%d'
    try:
        start = datetime.strptime(start_str, fmt)
        end   = datetime.strptime(end_str,   fmt)
    except ValueError as e:
        print(f'Invalid date format: {e}')
        sys.exit(1)
    if start > end:
        print(f'--start ({start_str}) must be <= --end ({end_str})')
        sys.exit(1)
    return start, end
```

**Simple banner pattern** (per CONTEXT.md D-16 — "simple text, not NEXUS ASCII art"):
```python
def print_banner() -> None:
    """Print a simple text banner for the backtester — no ASCII art."""
    print()
    print('  nexus_trader — Backtest Engine')
    print('  Rule-based daily OHLC simulation | NSE Nifty 100')
    print()
```

**main() body pattern** (argparse → validate → run → print report → save JSON):
```python
def main() -> None:
    args = parse_args()
    print_banner()
    start, end = validate_dates(args.start, args.end)

    capital = args.capital if args.capital is not None else config.CAPITAL
    bt = NexusBacktester(
        start_date=args.start,
        end_date=args.end,
        capital=capital,
    )

    logger.info('Running backtest %s → %s, capital=%.0f', args.start, args.end, capital)
    results = bt.run()

    _print_report(results)
    _save_results(results, args.start, args.end, capital)


if __name__ == '__main__':
    main()
```

**Report printing pattern** (per CONTEXT.md D-13 — tabulate with rounded_outline):
```python
def _print_report(results: dict) -> None:
    from tabulate import tabulate

    summary_rows = [
        ['Total Trades',       results['total_trades']],
        ['Win Rate',           f"{results['win_rate']:.1%}"],
        ['Total Net P&L',      f"Rs. {results['total_net_pnl']:,.2f}"],
        ['Total Return',       f"{results['total_return_pct']:.2%}"],
        ['Sharpe Ratio',       f"{results['sharpe_ratio']:.3f}"],
        ['Max Drawdown',       f"{results['max_drawdown_pct']:.2%}"],
        ['Profit Factor',      f"{results['profit_factor']:.2f}"],
    ]
    print('\n--- Backtest Summary ---')
    print(tabulate(summary_rows, headers=['Metric', 'Value'], tablefmt='rounded_outline'))

    monthly = results.get('monthly_returns', [])
    if monthly:
        monthly_rows = [
            [m['month'], m['trades'], f"Rs. {m['pnl']:,.2f}"]
            for m in monthly
        ]
        print('\n--- Monthly Returns ---')
        print(tabulate(monthly_rows, headers=['Month', 'Trades', 'Net P&L'], tablefmt='rounded_outline'))
```

**JSON save pattern** (per CONTEXT.md D-14 — logs/backtest/ directory):
```python
def _save_results(results: dict, start_str: str, end_str: str, capital: float) -> None:
    output_dir = Path('logs') / 'backtest'
    output_dir.mkdir(parents=True, exist_ok=True)   # parents=True for nested dirs
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filepath = output_dir / f'backtest_{ts}.json'
    payload = {**results, 'start_date': start_str, 'end_date': end_str, 'capital': capital}
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info('Results saved to %s', filepath)
```

Note: `Path("logs").mkdir(exist_ok=True)` pattern comes from `utils/logger.py` line 34. Extended here to `parents=True` for nested `logs/backtest/` directory.

---

### `execution/backtester.py` (service, batch)

**Analog A — class structure:** `config.py` lines 7–57 (class with `__init__`, private helpers, no external state)
**Analog B — brokerage math:** `03-CONTEXT.md` §"Brokerage calculation" D-07/D-08/D-09
**Analog C — yfinance batch download:** `02-PATTERNS.md` §"data/market_data.py" error return contract + 0.2s sleep pattern
**Analog D — is_trading_day usage:** `05-PATTERNS.md` §"NexusTrader public method pattern" lines 121–127
**Analog E — logger/config module header:** `main.py` lines 1–4 (import block) — every module with logic

**Imports pattern** (combines `main.py` header + data-layer yfinance imports):
```python
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd

from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)
```

**Class constructor pattern** (modeled on `config.py` class structure + CONTEXT.md D-05):
```python
class NexusBacktester:
    """Rule-based daily OHLC backtest engine. No AI agents, no API calls."""

    def __init__(
        self,
        start_date: str,
        end_date: str,
        capital: float | None = None,
    ) -> None:
        self.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        self.end_date   = datetime.strptime(end_date,   '%Y-%m-%d').date()
        self.capital    = capital if capital is not None else config.CAPITAL
        logger.info(
            'NexusBacktester initialised — %s to %s, capital=%.0f',
            start_date, end_date, self.capital
        )
```

**is_trading_day usage pattern** (from `05-PATTERNS.md` lines 121–127 — exact idiom to copy):
```python
# Inside day loop:
if not config.is_trading_day(current_date):
    logger.debug('Skipping %s (holiday or weekend)', current_date)
    current_date += timedelta(days=1)
    continue
```

**yfinance batch download pattern** (from `02-PATTERNS.md` §"0.2s rate-limit sleep" + CONTEXT.md D-10):
```python
def _fetch_day_data(self, symbols: list[str], trade_date: date) -> dict[str, dict]:
    """Fetch previous-day close + current-day OHLCV for all symbols.

    Returns dict keyed by symbol with 'prev_close', 'prev_volume', 'open',
    'high', 'low', 'close' keys. Missing symbols are silently omitted.
    """
    results = {}
    # Batch in groups of <=20 to stay within yfinance rate limits
    batch_size = 20
    symbol_list = list(symbols)
    for i in range(0, len(symbol_list), batch_size):
        batch = symbol_list[i:i + batch_size]
        try:
            df = yf.download(
                tickers=batch,
                period='5d',         # enough to get prev_close + trade_date
                interval='1d',
                group_by='ticker',
                auto_adjust=False,   # per CLAUDE.md — auto_adjust=True is the default in 0.2.40
                progress=False,
            )
            if df is None or df.empty:
                logger.debug('Empty batch response for %s ... (possible 429)', batch[0])
                time.sleep(0.2)
                continue
            # Flatten MultiIndex: df[symbol]['Close'] → df.xs(symbol, level=1, axis=1)
            for symbol in batch:
                try:
                    if len(batch) == 1:
                        sym_df = df
                    else:
                        sym_df = df.xs(symbol, level=1, axis=1)
                    if sym_df is None or sym_df.empty or len(sym_df) < 2:
                        logger.debug('Skipping %s — insufficient rows', symbol)
                        continue
                    # Find row for trade_date; prior row is prev_day
                    sym_df = sym_df.dropna(subset=['Close'])
                    trade_date_str = str(trade_date)
                    # Convert index to date strings for comparison
                    idx_dates = [str(d.date()) if hasattr(d, 'date') else str(d) for d in sym_df.index]
                    if trade_date_str not in idx_dates:
                        logger.debug('No data for %s on %s', symbol, trade_date)
                        continue
                    pos = idx_dates.index(trade_date_str)
                    if pos < 1:
                        logger.debug('No previous-day row for %s on %s', symbol, trade_date)
                        continue
                    prev_row = sym_df.iloc[pos - 1]
                    curr_row = sym_df.iloc[pos]
                    results[symbol] = {
                        'prev_close':  float(prev_row['Close']),
                        'prev_volume': float(prev_row['Volume']),
                        'open':        float(curr_row['Open']),
                        'high':        float(curr_row['High']),
                        'low':         float(curr_row['Low']),
                        'close':       float(curr_row['Close']),
                    }
                except Exception as e:
                    logger.debug('Symbol %s data extraction failed: %s', symbol, e)
                    continue
        except Exception as e:
            logger.warning('Batch download failed for %s...: %s', batch[0], e)
        time.sleep(0.2)   # mandatory 0.2s between batches — DATA-09 pattern
    return results
```

**Brokerage math pattern** (from `03-CONTEXT.md` D-07/D-08/D-09 — EXACT formula, duplicate not import):
```python
def _calculate_brokerage(self, buy_price: float, sell_price: float, qty: int) -> dict:
    """Zerodha brokerage formula. Duplicate of PaperPortfolio._calculate_brokerage.

    Per Phase 6 CONTEXT.md §Specifics: backtester duplicates this, does NOT import
    PaperPortfolio (avoids SQLite state pollution).

    Exchange charge rate: 0.0000307 (per 03-CONTEXT.md STATE.md correction — NOT 0.0000335).
    """
    turnover           = (buy_price + sell_price) * qty
    brokerage          = min(20.0, 0.0003 * turnover)          # 0.03% capped at Rs.20
    stt                = 0.00025 * sell_price * qty             # 0.025% sell-side only
    exchange_charges   = 0.0000307 * turnover                   # NSE exchange fee
    gst                = 0.18 * brokerage                       # 18% GST on brokerage
    total_charges      = brokerage + stt + exchange_charges + gst
    return {
        'brokerage':       brokerage,
        'stt':             stt,
        'exchange':        exchange_charges,
        'gst':             gst,
        'total_charges':   total_charges,
    }
```

**Per-day simulation pattern** (per CONTEXT.md D-07/D-08, using gap filter + R:R target/stop):
```python
def _simulate_day(
    self,
    trade_date: date,
    running_capital: float,
    equity_curve: list[float],
) -> tuple[list[dict], float]:
    """Simulate one trading day. Returns (trades_list, updated_capital).

    Gap filter: 1.5% <= gap_pct <= 8.0%, prev_volume >= 500k, 50 <= open <= 5000.
    Entry: open price. Target: entry * (1 + MIN_RR_RATIO * RISK_PER_TRADE_PCT).
    Stop:  entry * (1 - RISK_PER_TRADE_PCT).
    Exit logic: day_high >= target => WIN; day_low <= stop => LOSS; else EOD at close.
    When both target AND stop hit on same day: assume WIN (per CONTEXT.md D-07 specifics).
    """
    from data.universe import get_nse_universe
    symbols = [s['symbol'] for s in get_nse_universe()]
    day_data = self._fetch_day_data(symbols, trade_date)

    candidates = []
    for symbol, d in day_data.items():
        if d['prev_close'] <= 0:
            continue
        gap_pct = (d['open'] - d['prev_close']) / d['prev_close'] * 100
        if not (config.GAP_MIN_PCT <= gap_pct <= config.GAP_MAX_PCT):
            continue
        if d['prev_volume'] < config.MIN_PREV_VOLUME:
            continue
        if not (config.MIN_PRICE <= d['open'] <= config.MAX_PRICE):
            continue
        candidates.append((symbol, d, gap_pct))

    # Cap to MAX_OPEN_POSITIONS per day
    candidates = candidates[:config.MAX_OPEN_POSITIONS]

    trades = []
    daily_pnl = 0.0
    for symbol, d, gap_pct in candidates:
        entry       = d['open']
        risk_dec    = config.RISK_PER_TRADE_PCT           # 0.01
        target      = entry * (1 + config.MIN_RR_RATIO * risk_dec)
        stop        = entry * (1 - risk_dec)

        # Position sizing: risk 1% of running capital
        risk_amount = running_capital * risk_dec
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            continue
        qty = max(1, int(risk_amount / risk_per_share))

        # Exit logic — daily OHLC only
        # When both target and stop hit: assume WIN (daily-bar backtesting convention)
        if d['high'] >= target:
            exit_price = target
            exit_reason = 'TARGET'
        elif d['low'] <= stop:
            exit_price = stop
            exit_reason = 'STOP'
        else:
            exit_price = d['close']
            exit_reason = 'EOD'

        brokerage_info = self._calculate_brokerage(entry, exit_price, qty)
        gross_pnl = (exit_price - entry) * qty
        net_pnl   = gross_pnl - brokerage_info['total_charges']

        daily_pnl += net_pnl
        # Daily loss limit halt check (per CONTEXT.md D-07 step 7)
        if daily_pnl < -(config.DAILY_LOSS_LIMIT_PCT * running_capital):
            logger.info('Daily loss limit hit on %s — halting remaining trades', trade_date)
            break

        trades.append({
            'symbol':       symbol,
            'date':         str(trade_date),
            'entry':        entry,
            'exit':         exit_price,
            'qty':          qty,
            'gap_pct':      gap_pct,
            'exit_reason':  exit_reason,
            'gross_pnl':    gross_pnl,
            'net_pnl':      net_pnl,
            'charges':      brokerage_info['total_charges'],
        })

    running_capital += daily_pnl
    equity_curve.append(running_capital)
    return trades, running_capital
```

**run() method and metrics calculation** (per CONTEXT.md D-12/D-15 — 8 required keys):
```python
def run(self) -> dict:
    """Run the full backtest. Returns dict with exactly 8 metric keys.

    Keys: total_trades, win_rate, total_net_pnl, total_return_pct,
          sharpe_ratio, max_drawdown_pct, profit_factor, monthly_returns.
    """
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
                '%s: %d trades, daily equity=%.2f',
                current_date, len(day_trades), running_capital
            )
        current_date += timedelta(days=1)

    return self._compute_metrics(all_trades, equity_curve, trading_days_processed)

def _compute_metrics(
    self,
    trades: list[dict],
    equity_curve: list[float],
    trading_days_processed: int,
) -> dict:
    """Compute the 8 required backtest metrics."""
    total_trades = len(trades)
    wins   = [t for t in trades if t['net_pnl'] > 0]
    losses = [t for t in trades if t['net_pnl'] <= 0]
    win_rate = len(wins) / total_trades if total_trades > 0 else 0.0

    total_net_pnl    = sum(t['net_pnl'] for t in trades)
    total_return_pct = total_net_pnl / self.capital if self.capital > 0 else 0.0

    # Sharpe ratio on daily equity returns (per CONTEXT.md D-15)
    # daily_return[i] = (equity[i+1] - equity[i]) / capital
    daily_returns = [
        (equity_curve[i + 1] - equity_curve[i]) / self.capital
        for i in range(len(equity_curve) - 1)
    ] if len(equity_curve) > 1 else []
    if daily_returns:
        mean_r = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
        std_r = math.sqrt(variance)
        sharpe_ratio = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0
    else:
        sharpe_ratio = 0.0

    # Max drawdown on equity curve
    peak = equity_curve[0]
    max_drawdown_pct = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_drawdown_pct:
            max_drawdown_pct = dd

    # Profit factor = gross_wins / abs(gross_losses)
    gross_wins   = sum(t['net_pnl'] for t in wins)
    gross_losses = abs(sum(t['net_pnl'] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    # Monthly returns (per CONTEXT.md D-12 — list of {month, pnl, trades})
    from collections import defaultdict
    monthly: dict[str, dict] = defaultdict(lambda: {'pnl': 0.0, 'trades': 0})
    for t in trades:
        month_key = t['date'][:7]   # 'YYYY-MM'
        monthly[month_key]['pnl']    += t['net_pnl']
        monthly[month_key]['trades'] += 1
    monthly_returns = [
        {'month': k, 'pnl': v['pnl'], 'trades': v['trades']}
        for k, v in sorted(monthly.items())
    ]

    return {
        'total_trades':           total_trades,
        'win_rate':               win_rate,
        'total_net_pnl':          total_net_pnl,
        'total_return_pct':       total_return_pct,
        'sharpe_ratio':           sharpe_ratio,
        'max_drawdown_pct':       max_drawdown_pct,
        'profit_factor':          profit_factor,
        'monthly_returns':        monthly_returns,
        # Bonus key for JSON save (not in D-12 required 8, but useful)
        'trading_days_processed': trading_days_processed,
    }
```

**Error return contract** (from `02-PATTERNS.md` §"Error return contract" — identical convention):
- `_fetch_day_data()` returns empty `{}` on total failure; individual symbols skipped silently
- `run()` returns dict with zeroed metrics on empty date range (never raises to caller)
- All methods wrapped in `try/except Exception as e` with `logger.error(...)` and safe fallback

---

### `README.md` (documentation)

**Analog:** None — first README in the project.

Per CONTEXT.md D-18/D-19: single file at project root. Sections: Overview, Prerequisites, `.env` Setup, Run Modes, Project Structure. Practical tone. No architecture diagrams.

Run modes section must include exactly three code blocks:
```
python main.py
python main.py --dry-run
python backtest.py --start YYYY-MM-DD --end YYYY-MM-DD [--capital FLOAT]
```

The four required `.env` keys (from `config.py` `_require()` calls, lines 10–13):
- `GEMINI_API_KEY` — from Google AI Studio (aistudio.google.com)
- `ANTHROPIC_API_KEY` — from Anthropic Console (console.anthropic.com)
- `TELEGRAM_BOT_TOKEN` — from BotFather on Telegram
- `TELEGRAM_CHAT_ID` — from Telegram (your chat ID)

---

## Shared Patterns

### Logger instantiation
**Source:** `utils/logger.py` lines 9–54 + `main.py` lines 1–4
**Apply to:** `execution/backtester.py`, `backtest.py`

```python
from utils.logger import setup_logger
logger = setup_logger(__name__)
```

`setup_logger(__name__)` is idempotent (checks `logger.handlers` before adding). Returns a logger with colored terminal output + 30-day rotating file handler at `logs/nexus_YYYY-MM-DD.log`. Both `backtest.py` and `execution/backtester.py` use module-level logger.

### Config access
**Source:** `config.py` lines 1–57 (existing) + `05-PATTERNS.md` §"Config access"
**Apply to:** `execution/backtester.py`, `backtest.py`, `main.py` (unchanged)

```python
from config import config
# Used in backtester: config.CAPITAL, config.GAP_MIN_PCT, config.GAP_MAX_PCT,
#   config.MIN_PREV_VOLUME, config.MIN_PRICE, config.MAX_PRICE,
#   config.RISK_PER_TRADE_PCT, config.MIN_RR_RATIO, config.MAX_OPEN_POSITIONS,
#   config.DAILY_LOSS_LIMIT_PCT, config.is_trading_day(d)
```

Never import individual attributes — always `from config import config` and access via dot notation.

### Return-None-on-failure contract
**Source:** `02-PATTERNS.md` §"Error return contract" + `05-PATTERNS.md` §"Return-None-on-failure contract"
**Apply to:** All `NexusBacktester` methods

| Return type | Failure value |
|---|---|
| `dict` (day data) | `{}` empty dict |
| `list` (trades) | `[]` empty list |
| `float` | `0.0` |
| `tuple` | safe zero-value tuple |

Every method wraps body in `try/except Exception as e` and calls `logger.error(...)` or `logger.debug(...)` before returning the fallback.

### yfinance rate limit guard
**Source:** `02-PATTERNS.md` §"0.2s rate-limit sleep" (DATA-09 pattern) + CLAUDE.md §"1. yfinance / Rate Limiting Behavior"
**Apply to:** `execution/backtester.py` `_fetch_day_data()` all batch loops

```python
import time
# After every yf.download() batch call (regardless of success or failure):
time.sleep(0.2)
```

Also: `auto_adjust=False` is required (CLAUDE.md — `auto_adjust=True` became the default in 0.2.x; raw prices needed for brokerage math accuracy).

### Path + directory creation
**Source:** `utils/logger.py` line 34 + `02-PATTERNS.md` §"Path + directory creation"
**Apply to:** `backtest.py` `_save_results()` for `logs/backtest/` directory

```python
from pathlib import Path
Path('logs/backtest').mkdir(parents=True, exist_ok=True)
# parents=True for nested dirs; exist_ok=True makes it idempotent
```

---

## Design Notes for Planner

### Date override for --dry-run mode in `main.py`
CONTEXT.md D-01 says dry-run calls `run_pre_market_pipeline()` "using yesterday's date". The Phase 5 `run_pre_market_pipeline()` internally calls `datetime.now(ist).date()` for the holiday check. Two implementation strategies:

**Option A (recommended):** Add an optional `date_override: date | None = None` parameter to `run_pre_market_pipeline()`. When `main.py` dry-run branch calls it, pass `datetime.now(ist).date() - timedelta(days=1)`. Keeps the override explicit and testable.

**Option B:** Patch `datetime.now` in `main.py` dry-run branch before calling the method. Fragile — not recommended.

The planner must pick one and document it in the Phase 6 PLAN.

### Brokerage math exchange rate
Use `0.0000307` — NOT `0.0000335`. This correction is from `03-CONTEXT.md` §"Specifics" quoting STATE.md. The CLAUDE.md project constraints mention 0.00335% which rounds to 0.0000335 — but STATE.md correction supersedes it. The backtester must use 0.0000307 to match `PaperPortfolio` exactly.

### MultiIndex flattening for single-ticker vs multi-ticker `yf.download()`
When `len(batch) == 1`, `yf.download()` returns a flat DataFrame (no MultiIndex). When `len(batch) > 1`, it returns a MultiIndex. The `_fetch_day_data` pattern above handles both cases with the `if len(batch) == 1: sym_df = df else: sym_df = df.xs(...)` branch.

---

## No Analog Found

`README.md` is the only file with no codebase analog. Use CONTEXT.md D-18/D-19 as the complete specification.

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `README.md` | documentation | static | No documentation files exist in the codebase |

---

## Metadata

**Analog search scope:** `C:\Users\katuk\OneDrive\Desktop\projects\stockss` (all `.py` files + planning docs through Phase 5)
**Source files scanned:** `config.py`, `utils/logger.py`, `main.py`, `execution/__init__.py`, `agents/__init__.py`, `data/__init__.py`
**Plan files referenced:** `05-PATTERNS.md`, `05-01-PLAN.md`, `05-02-PLAN.md`, `03-CONTEXT.md`, `02-PATTERNS.md`
**Pattern extraction date:** 2026-06-06
**Note:** Codebase is Phase 1–stub level. `execution/scheduler.py`, `execution/portfolio.py`, `data/universe.py`, all agent files are planned but not yet written. All patterns for Phase 6 are derived from: (1) the three existing source files, (2) Phase 5 PATTERNS.md which contains fully verified implementation patterns for `main.py` and `execution/scheduler.py`, and (3) Phase 3 CONTEXT.md for the authoritative brokerage formula.
