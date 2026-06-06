# Phase 6: Dry-Run & Backtest - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in 06-CONTEXT.md — this log preserves the discussion.

**Date:** 2026-06-06
**Phase:** 06-dry-run-backtest
**Mode:** discuss
**Areas discussed:** --dry-run behavior, Backtester engine, Data granularity, Report output format

---

## Area 1: --dry-run Mode Behavior

| Question | Options | Selected |
|----------|---------|----------|
| When --dry-run is passed, what should happen? | One-shot: run pre-market, print watchlist, exit / Live modifier: scheduler runs, orders skipped / Both: separate --validate flag | One-shot: run pre-market, print watchlist, exit (Recommended) |

**Decision:** `--dry-run` is a one-shot mode. `main.py` runs `NexusTrader.run_pre_market_pipeline()` once on yesterday's date, prints the watchlist table, then exits. APScheduler never starts. This changes Phase 5's `--dry-run` implementation (was: "skip orders during live trading").

**Impact on Phase 5:** Phase 5's `NexusTrader(dry_run=True)` order-skipping behavior is superseded. The `dry_run` constructor flag may be simplified or removed.

---

## Area 2: Backtester Engine

| Question | Options | Selected |
|----------|---------|----------|
| Should NexusBacktester call real AI agents or simulate rules directly? | Rule-based simulation only / Reuse AI agents / Hybrid: rules + AgentI4 | Rule-based simulation only (Recommended) |

**Decision:** `NexusBacktester` is rule-based only. No Gemini API calls, no agent instantiation. Reads yfinance daily OHLCV data, applies gap filter + strategy rules + brokerage math. 60+ day backtest runs in seconds.

**Rationale:** API costs and rate limits make per-day AI agent calls impractical for backtesting. Rule consistency is more valuable than AI-ranking consistency for strategy validation.

---

## Area 3: Data Granularity

| Question | Options | Selected |
|----------|---------|----------|
| What data granularity for simulating intraday entries/exits? | Daily OHLC only / 5-minute intraday / 1-hour bars | Daily OHLC only (Recommended) |

**Decision:** Daily OHLC. Entry = open price. Target hit = if `day_high >= target`. Stop hit = if `day_low <= stop`. Neither = EOD exit at `day_close`. Fast, no rate limit risk, covers any date range.

**Edge case locked:** When both target and stop would be hit on the same day, assume WIN (target hit first). Standard convention for daily-bar backtesting.

---

## Area 4: Backtest Report Output

| Question | Options | Selected |
|----------|---------|----------|
| Where should the backtest report go? | Terminal tabulate + JSON file / Terminal only / Terminal + CSV | Terminal tabulate + save to JSON file (Recommended) |

**Decision:** Print formatted tabulate report to terminal (summary metrics + monthly returns table). Also save full results to `logs/backtest/backtest_YYYYMMDD_HHmmss.json`. JSON enables later analysis or comparison runs.

---

## Deferred Ideas

- Telegram alerts for backtest completion → ALRT-01/v2
- Equity curve chart → v2
- Nifty 500 universe in backtester → UNIV-01/v2
- Short selling simulation → SHRT-01/v2
- Walk-forward parameter optimization → out of scope
