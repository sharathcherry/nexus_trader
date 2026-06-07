---
phase: 05-orchestrator-scheduler
plan: 02
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 5-02 — TradingScheduler + main.py

## Outcome
`execution/scheduler.py` complete with `NexusTrader` and `TradingScheduler`. `main.py` implements `--dry-run` branch and live path.

## Key Implementation Details

### TradingScheduler
`BackgroundScheduler(executors={"default": ThreadPoolExecutor(max_workers=1)}, timezone=IST)`. Three jobs: pre_market (08:30), market_session (OrTrigger 09:15–15:15 every 60s), post_market (15:35). `max_instances=1` on all jobs.

### run_pre_market_pipeline date_override
`date_override: date | None = None` parameter added. `today = date_override if date_override is not None else datetime.now(ist).date()`.

### Event loop conflict handling
`asyncio.run()` may raise `RuntimeError` if event loop already running (in scheduler thread). Falls back to `ThreadPoolExecutor` for single-thread execution.

### Watchlist gate
`_watchlist_ready` asyncio.Event set on ALL exit paths (including exceptions) in `run_pre_market_pipeline`.
