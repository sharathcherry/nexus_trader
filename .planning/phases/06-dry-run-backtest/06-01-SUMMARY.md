---
phase: 06-dry-run-backtest
plan: 01
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 6-01 — Dry-Run Mode

## Outcome
`main.py` rewritten with `--dry-run` branch. `execution/scheduler.py` updated with `date_override` parameter.

## Key Details
- `run_pre_market_pipeline(self, date_override: date | None = None)` — default None falls back to `datetime.now(ist).date()`
- Dry-run: `NexusTrader(dry_run=False)` → `run_pre_market_pipeline(date_override=yesterday)` → `sys.exit(0)`
- TradingScheduler never instantiated in dry-run path
- Live path unchanged from Phase 5 spec
