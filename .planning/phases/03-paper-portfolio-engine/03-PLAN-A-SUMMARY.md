---
phase: "03"
plan: "03-PLAN-A"
subsystem: "execution"
tags: [sqlite, portfolio, brokerage, paper-trading]
dependency_graph:
  requires: [config.CAPITAL, config.MAX_OPEN_POSITIONS, config.MAX_TRADES_PER_DAY, config.DAILY_LOSS_LIMIT_PCT]
  provides: [PaperPortfolio, execution/portfolio.db]
  affects: [execution/order_manager.py, agents/I4, agents/I9, main.py]
tech_stack:
  added: [sqlite3 (stdlib), pytz]
  patterns: [SQLite WAL mode, write-through persistence, meta key-value table, Zerodha brokerage math]
key_files:
  created: [execution/portfolio.py]
  modified: []
decisions:
  - "Used sqlite3 stdlib directly — thin enough for one-file schema, no ORM needed"
  - "WAL journal_mode=WAL set on every _get_conn() call — ensures consistency under concurrent read"
  - "Write-through on every trade — no background flush, survives process crash"
  - "daily_pnl crossing -2% of CAPITAL (Rs-2000) sets is_halted=True; resets on new trading day"
  - "force_squaredoff flag set BEFORE closing positions (crash safety — prevents partial re-close)"
  - "Exchange charge rate confirmed: 0.0000307 (STATE.md correction, not 0.0000335 in PROJECT.md)"
metrics:
  duration_minutes: 16
  completed: "2026-06-06"
  tasks_completed: 7
  files_created: 1
---

# Phase 3 Plan A: PaperPortfolio Summary

**One-liner:** SQLite WAL-backed paper portfolio with Zerodha brokerage math (0.0000307 exchange rate), write-through buy/sell/partial_exit, daily reset, halt logic, and idempotent force squareoff.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| A-1 | DB init + schema (positions, trades, meta tables, WAL mode) | 82bbd63 |
| A-2 | _calculate_brokerage() + capital/daily_pnl/trade_count/is_halted properties | 82bbd63 |
| A-3 | buy() with halt/max-position/max-trade/duplicate guards | 82bbd63 |
| A-4 | sell() with brokerage math and halt threshold check | 82bbd63 |
| A-5 | partial_exit() and update_stop_loss() (trailing upward only) | 82bbd63 |
| A-6 | get_portfolio_summary() and get_daily_report() | 82bbd63 |
| A-7 | force_squareoff_all() with idempotency flag (crash-safe) | 82bbd63 |

## Verification Results

- `net_pnl` for buy@500/sell@550/qty=10: Rs494.5856 (target Rs494.586 — within Rs0.01)
- 6th buy() returns False (max 5 open positions)
- buy() on halted portfolio returns False (WARNING logged)
- daily_pnl crossing -Rs2000 sets is_halted=True
- Open positions survive process restart (SQLite persistence verified)
- WAL journal_mode confirmed on every connection
- force_squareoff_all() idempotent: second call returns 0

## Brokerage Math Verification (manual)

Buy 10 @ Rs500, Sell 10 @ Rs550:
- turnover = 10500
- brokerage = min(20, 0.0003 * 10500) = Rs3.15
- STT = 0.00025 * 5500 = Rs1.375
- exchange = 0.0000307 * 10500 = Rs0.3224
- GST = 0.18 * 3.15 = Rs0.567
- total_charges = Rs5.4144
- gross_pnl = Rs500.00
- net_pnl = Rs494.5856

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria met.

## Known Stubs

None.

## Threat Flags

None. execution/portfolio.db is local file, no network surface, no auth paths.

## Self-Check: PASSED

- execution/portfolio.py exists: FOUND
- Commit 82bbd63 exists: FOUND
- Brokerage math matches manual calculation: VERIFIED
- All 7 acceptance criteria confirmed via automated test
