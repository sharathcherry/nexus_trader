# Phase 6: Dry-Run & Backtest - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate the full pipeline on historical data before any live session is trusted. Delivers three capabilities: (1) one-shot `--dry-run` mode that runs pre-market pipeline on yesterday's data and exits without starting the scheduler; (2) `NexusBacktester` — a pure rule-based engine that replays trading days between a date range using daily OHLC data and produces 8 strategy-level performance metrics; (3) `README.md` documenting installation, `.env` setup, and all three run modes.

New files: `backtest.py` (entry point), `execution/backtester.py` (NexusBacktester class), `README.md`.
Modified file: `main.py` (--dry-run behavior changed to one-shot).

</domain>

<decisions>
## Implementation Decisions

### --dry-run Mode Behavior (TEST-01, TEST-02)
- **D-01:** `--dry-run` is a **one-shot mode**: when passed, `main.py` runs `NexusTrader.run_pre_market_pipeline()` once using yesterday's date (override `datetime.now(ist).date() - timedelta(days=1)`), prints the watchlist table, then exits (`sys.exit(0)`). The APScheduler (TradingScheduler) is NEVER started in dry-run mode.
- **D-02:** This changes Phase 5's `--dry-run` implementation. Phase 5 wired `NexusTrader(dry_run=True)` to skip orders during live trading. Phase 6 replaces this: dry-run now means one-shot pre-market execution, not a live-mode modifier. The `dry_run` constructor parameter on `NexusTrader` is repurposed or removed — `main.py` handles the branch before instantiating `TradingScheduler`.
- **D-03:** In `main.py`, the dry-run branch is:
  ```python
  if args.dry_run:
      trader = NexusTrader(dry_run=False)  # live agents, no order skipping
      trader.run_pre_market_pipeline()     # runs on yesterday's date
      sys.exit(0)
  # else: normal live path with TradingScheduler
  ```
  No banner mode difference — print_banner(dry_run=True) still shows "DRY-RUN" in the info block.

### NexusBacktester Engine (TEST-03, TEST-04, TEST-05)
- **D-04:** `NexusBacktester` is **rule-based only** — no AI agents called. No Gemini API calls, no rate limit risk. Reads yfinance daily OHLCV data directly (`yf.download()` with `interval='1d'`).
- **D-05:** `class NexusBacktester` in `execution/backtester.py`. Constructor: `NexusBacktester(start_date: str, end_date: str, capital: float = None)`. Uses `config.CAPITAL` as default capital. `run()` method returns a dict with 8 metrics.
- **D-06:** Day loop: iterate from `start_date` to `end_date` (inclusive). For each date, call `config.is_trading_day(d)` — skip weekends and NSE holidays (reuses Phase 5 implementation). Only process trading days.
- **D-07:** Per trading day simulation:
  1. Fetch previous day's close and today's open for all Nifty 100 symbols (yfinance batch download)
  2. Compute `gap_pct = (open - prev_close) / prev_close * 100`
  3. Filter: `1.5% <= gap_pct <= 8.0%` AND `prev_volume >= 500_000` AND `50 <= open <= 5000`
  4. For each filtered symbol: `entry_price = open`; `target = entry * (1 + min_rr * risk_pct / 100)`; `stop = entry * (1 - risk_pct / 100)` where `risk_pct = config.RISK_PER_TRADE_PCT * 100`
  5. Exit logic using daily OHLC: if `day_high >= target` → WIN; if `day_low <= stop` → LOSS; else → EOD exit at `day_close` (may be small profit or loss)
  6. Apply Zerodha brokerage math: `min(20, 0.03% * turnover) + STT 0.025% + exchange 0.00335% + 18% GST`
  7. Apply `config.MAX_OPEN_POSITIONS` cap per day; apply `config.DAILY_LOSS_LIMIT_PCT` halt check
- **D-08:** `min_rr` (minimum risk:reward used for target calculation) = `config.MIN_RR_RATIO` (1.5). Target = `entry * (1 + 1.5 * risk_pct_decimal)`.

### Data Granularity (TEST-03, TEST-04)
- **D-09:** Daily OHLC only — no intraday data fetched. Entry assumed at open price. Target hit checked against daily high. Stop hit checked against daily low. EOD exit at daily close if neither target nor stop hit.
- **D-10:** Data fetch strategy: use `yf.download(tickers, period='2d', interval='1d', group_by='ticker', auto_adjust=False)` to get previous day + current day in one call. Flatten MultiIndex columns with `.xs()` or `droplevel`. Apply `time.sleep(0.2)` between batches of ≤20 symbols (yfinance rate limit guard from Phase 2 patterns).
- **D-11:** If yfinance returns empty data for a symbol on a given day (delisted, trading halt, or 429): skip that symbol silently, log at DEBUG.

### Backtest Report Output (TEST-05, TEST-06)
- **D-12:** `NexusBacktester.run()` returns a dict with exactly 8 keys: `total_trades`, `win_rate`, `total_net_pnl`, `total_return_pct`, `sharpe_ratio`, `max_drawdown_pct`, `profit_factor`, `monthly_returns` (list of `{month: str, pnl: float, trades: int}`).
- **D-13:** `backtest.py` prints a formatted terminal report using `tabulate` — two tables: (1) summary metrics table (label, value), (2) monthly returns table (month, trades, net P&L, return%). Uses `tablefmt="rounded_outline"`.
- **D-14:** Also save full results to `logs/backtest/backtest_YYYYMMDD_HHmmss.json` (ISO datetime in filename, create dir if absent). JSON includes all 8 metrics plus `start_date`, `end_date`, `capital`, `trading_days_processed`.
- **D-15:** Sharpe ratio calculation: `sharpe = (mean_daily_return / std_daily_return) * sqrt(252)`. Daily return = `net_pnl / capital`. If `std_daily_return == 0` → sharpe = 0.

### backtest.py Entry Point (TEST-06)
- **D-16:** `backtest.py` at project root. `argparse` with `--start YYYY-MM-DD` (required), `--end YYYY-MM-DD` (required), `--capital FLOAT` (optional, default `config.CAPITAL`). Validates dates with `datetime.strptime`. Prints banner (simple text, not NEXUS ASCII art).
- **D-17:** Import pattern: `from execution.backtester import NexusBacktester`. No scheduler, no agents instantiated in `backtest.py`.

### README.md (TEST-07)
- **D-18:** Single `README.md` at project root. Sections: (1) Overview, (2) Prerequisites & Installation (`pip install -r requirements.txt`), (3) `.env` Setup (list all 4 keys with source links: Google AI Studio, Anthropic console), (4) Run Modes (three code blocks: `python main.py`, `python main.py --dry-run`, `python backtest.py --start ... --end ...`), (5) Project Structure (brief tree). No architecture diagram.
- **D-19:** README tone: practical, no marketing fluff. Target reader is the developer returning to the project after a break.

### Claude's Discretion
- Exact Sharpe ratio implementation (annualization factor, handling zero std)
- Whether max_drawdown is computed on daily equity curve or trade-by-trade
- Exact tabulate column formatting in terminal report
- Whether `backtest.py` banner uses colorlog or plain print

</decisions>

<specifics>
## Specific Ideas

- D-07 exit logic: "if day_high >= target → WIN" assumes the target was hit before the stop. For daily OHLC, when both target and stop are hit on the same day, assume WIN (conservative — favors the strategy). This is standard for daily-bar backtesting.
- Brokerage math is already implemented in `execution/portfolio.py` — backtester should duplicate or reuse the calculation function (not import PaperPortfolio to avoid state pollution).
- `time.sleep(0.2)` between yfinance batch calls is mandatory (Phase 2 decision DATA-09 pattern).

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Backtest simulation rules
- `.planning/REQUIREMENTS.md` §"Dry-Run & Backtest" (TEST-01 through TEST-07) — complete requirement set
- `.planning/phases/05-orchestrator-scheduler/05-CONTEXT.md` — D-01 through D-06: --dry-run flag pattern, NexusTrader constructor, is_trading_day() usage
- `.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md` — Brokerage math formula (Zerodha), PaperPortfolio interface

### Config constants used
- `config.py` — `CAPITAL`, `RISK_PER_TRADE_PCT`, `MIN_RR_RATIO`, `MAX_OPEN_POSITIONS`, `DAILY_LOSS_LIMIT_PCT`, `GAP_MIN_PCT`, `GAP_MAX_PCT`, `NSE_HOLIDAYS_2026`, `is_trading_day()`

### Data fetching patterns
- `.planning/phases/02-data-layer/02-CONTEXT.md` — yfinance batch download pattern, 0.2s delay, MultiIndex flattening, empty DataFrame handling
- `CLAUDE.md §"1. yfinance"` — rate limit behavior, auto_adjust default, NSE timezone issues

### Phase goal
- `.planning/ROADMAP.md` §"Phase 6: Dry-Run & Backtest" — 4 success criteria define done

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (exist after Phases 1–5)
- `config.py` → `config.is_trading_day(d)`, `config.NSE_HOLIDAYS_2026`, all trading params — reuse directly in backtester
- `execution/portfolio.py` → Zerodha brokerage formula — duplicate into backtester (no shared state)
- `utils/logger.py` → `setup_logger(__name__)` — standard module-level logger
- `data/nse_universe.py` (or equivalent from Phase 2) → Nifty 100 symbols list
- `main.py` → existing `parse_args()`, `print_banner()` — extend parse_args for --dry-run one-shot branch

### Established Patterns
- Error contract: methods return None/empty on failure, never raise to caller
- `from config import config` + `logger = setup_logger(__name__)` at module level
- yfinance: `auto_adjust=False`, 0.2s sleep between calls, empty DataFrame guard
- `time.sleep(0.2)` between sequential yfinance calls (DATA-09)

### Integration Points
- `backtest.py` → `execution/backtester.py` NexusBacktester (one-way: backtest.py calls, no reverse)
- `main.py` (--dry-run branch) → `execution/scheduler.py` NexusTrader.run_pre_market_pipeline() (already exists after Phase 5)
- NexusBacktester → `config.py` (params + is_trading_day)
- NexusBacktester → yfinance (data fetch)
- NexusBacktester → `tabulate` + json (output)
- `backtest.py` output → `logs/backtest/` directory

</code_context>

<deferred>
## Deferred Ideas

- Telegram alerts for backtest completion — ALRT-01/v2 scope
- Equity curve chart (matplotlib) — v2, out of scope
- Nifty 500 universe in backtester — UNIV-01 v2 scope
- Walk-forward optimization of parameters — out of scope
- Short selling simulation — SHRT-01 v2 scope
- Parallel yfinance fetching with asyncio — out of scope (0.2s serial delay is authoritative)

</deferred>

---

*Phase: 06-dry-run-backtest*
*Context gathered: 2026-06-06*
