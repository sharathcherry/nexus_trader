---
phase: 06-dry-run-backtest
plan: 02
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 6-02 — NexusBacktester

## Outcome
`execution/backtester.py` implemented and verified.

## Key Details
- Exchange rate `0.0000307`; brokerage = `min(20.0, 0.0003 * turnover)`
- TARGET exit takes priority over STOP on same day (WIN branch checked first)
- Sharpe = `(mean_r / std_r) * sqrt(252)`; profit_factor = `gross_wins / abs(gross_losses)`
- `config.is_trading_day()` used to skip non-trading days
- Batch fetches of 20 symbols, `time.sleep(0.2)` between batches
- `auto_adjust=False` to get raw OHLC prices
