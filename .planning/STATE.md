---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: complete
last_updated: "2026-06-07T01:45:00.000Z"
progress:
  total_phases: 8
  completed_phases: 8
  total_plans: 19
  completed_plans: 19
  percent: 100
---

# STATE: nexus_trader

**Project:** nexus_trader — NSE India Intraday Paper Trading System
**Last updated:** 2026-06-11
**Updated by:** orchestrator (quick task 260611-96a — critical bug fixes C1-C7)

Last activity: 2026-06-11 - Completed quick task 260611-96a: Fix critical bugs C1-C7 from BUGS.md

---

## Project Reference

**Core Value:** A reliable daily paper trading pipeline that wakes up at 8:30 AM IST, runs without intervention through 3:30 PM, and produces a reviewed trade ledger — proving the strategy logic works before any real capital is risked.

**Current Focus:** COMPLETE — all phases delivered

---

## Current Position

**Active Phase:** None
**Active Plan:** None
**Phase Status:** All phases complete
**Overall Status:** Full pipeline delivered — pre-market, market session, post-market, orchestrator, dry-run, backtest

```
Progress: [████████████████████████████████████████] 100% (8/8 phases)
```

| Phase | Status |
|-------|--------|
| 1. Foundation | Complete |
| 2. Data Layer | Complete |
| 3. Paper Portfolio Engine | Complete |
| 4a. Pre-Market Agents (I0, I1, I2, I3) | Complete |
| 4b. Market Session Agents (I4, I6) + Tests | Complete |
| 4c. Post-Market Agent (I9) + Tests | Complete |
| 5. Orchestrator & Scheduler | Complete |
| 6. Dry-Run & Backtest | Complete |

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Phases complete | 8/8 |
| Test suite | 73 tests, all passing |
| Plans complete | 19/19 |
| Blockers active | 0 |

---

## Delivered Artifacts

| File | Purpose |
|------|---------|
| `main.py` | Entry point — live mode + `--dry-run` one-shot |
| `backtest.py` | CLI entry for NexusBacktester |
| `config.py` | Config singleton + is_trading_day() + NSE holidays 2026 |
| `agents/agent_i0.py` | Universe scanner (pre-market) |
| `agents/agent_i1.py` | Gap screener (pre-market) |
| `agents/agent_i2.py` | Gemini Flash ranker (pre-market) |
| `agents/agent_i3.py` | Watchlist builder (pre-market) |
| `agents/agent_i4.py` | Signal engine — 60s async polling loop |
| `agents/agent_i6.py` | Position monitor — exits, trailing SL, circuit detection |
| `agents/agent_i9.py` | Claude Sonnet post-market reviewer |
| `execution/scheduler.py` | NexusTrader + TradingScheduler (APScheduler BackgroundScheduler) |
| `execution/portfolio.py` | PaperPortfolio (SQLite WAL) |
| `execution/order_manager.py` | OrderManager (qty sizing, exit logic) |
| `execution/backtester.py` | NexusBacktester — rule-based OHLC replay |
| `data/universe.py` | Nifty 100 symbol list |
| `data/market_data.py` | MarketDataFetcher (yfinance) |
| `data/indicators.py` | Indicators (VWAP, EMA, RSI, ATR, ORB — inline pandas) |
| `utils/logger.py` | colorlog setup + custom levels TRADE/PNL_PROFIT/PNL_LOSS |
| `tests/` | 73 unit tests across all agents and modules |
| `README.md` | Developer docs — 5 sections, 3 run modes, 4 env keys |

---

## Accumulated Context

### Key Decisions Made

| Decision | Rationale | Phase |
|----------|-----------|-------|
| `google-genai>=2.0.0` not `google-generativeai` | Deprecated/frozen Nov 2025 | 1 |
| Inline pandas Indicators, no `ta` library | `ta==0.11.0` has unfixed pandas 2.x bugs | 2 |
| SQLite WAL mode for position state | Survives restart; no read/write contention | 3 |
| Exchange charge rate: 0.0000307 not 0.0000335 | Zerodha actual rate; PROJECT.md spec was wrong | 3 |
| `BackgroundScheduler` not `BlockingScheduler` | BlockingScheduler prevents async loop from running | 5 |
| `await asyncio.sleep(60)` not `time.sleep(60)` | `time.sleep()` blocks event loop | 4b/5 |
| Force square-off idempotent `_squaredoff` guard | APScheduler job AND loop time check both call it safely | 4b |
| I0+I1 concurrent via `asyncio.gather`, I2→I3 sequential | I0/I1 independent; I2 needs I1 output; I3 needs I2 output | 4a |
| `watchlist_ready` asyncio.Event | Prevents market-open job firing before pre-market completes | 4a/5 |
| Circuit deque maxlen=3 (one price per polling cycle) | Detects frozen price across 3 separate 60s cycles, not 3 rows in one DataFrame | 4b |
| Backtester TARGET exit before STOP on same day | WIN takes priority; prevents same-day STOP from overriding a TARGET hit | 6 |
| `prepost=False` on all yfinance calls | Pre-open indicative candles (09:00–09:15) unreliable | 2 |

### Critical Pitfalls Documented

1. `google-generativeai` is deprecated — all Gemini imports use `from google import genai`
2. yfinance NSE data is 15 minutes delayed — log at startup, embed in every trade record
3. Corporate actions create false gap signals — AgentI1 filters ex-dividend/bonus/split dates
4. `ta` 0.11.0 pandas 2.x incompatibility — replaced with inline pandas implementations
5. `time.sleep(60)` blocks async event loop — use `await asyncio.sleep(60)` everywhere
6. `max_instances` not set causes job overlap — set on every APScheduler `add_job()` call
7. Exchange charge rate in PROJECT.md is incorrect (0.0000335 vs actual 0.0000307)
8. Windows→Linux mount mtime: Edit tool writes via Windows but Linux VM sees stale mtime. Always write files from bash shell in VM to force fresh content pickup by pytest.
9. `get_final_message()` must be INSIDE the `with client.messages.stream(...) as stream:` block
10. `portfolio.sell()` requires qty parameter; `portfolio.partial_exit()` requires (symbol, price, int_qty, reason)

### Todos (Active)

- [x] Phase 1 — Foundation complete
- [x] Phase 2 — Data Layer complete
- [x] Phase 3 — Paper Portfolio Engine complete
- [x] Phase 4a — Pre-Market Agents complete
- [x] Phase 4b — Market Session Agents + Tests complete (73 tests passing)
- [x] Phase 4c — Post-Market Agent complete
- [x] Phase 5 — Orchestrator & Scheduler complete
- [x] Phase 6 — Dry-Run & Backtest complete

### Blockers

None.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260611-96a | Fix critical bugs C1-C7 from BUGS.md (_safe_fetch signature, token refresh chain, cache TTL, circuit ordering, daily reset, restart deadlock, shutdown liquidation) | 2026-06-11 | bb73653 | [260611-96a-fix-critical-bugs-from-bugs-md-c1-safe-f](./quick/260611-96a-fix-critical-bugs-from-bugs-md-c1-safe-f/) |

### Bug Tracker (BUGS.md)

| ID | Severity | Status | Commit |
|----|----------|--------|--------|
| C1 _safe_fetch signature | Critical | **FIXED** | 08c1c91 |
| C2 Upstox token refresh chain | Critical | **FIXED** (code) — VM still needs `pip install undetected-chromedriver pyotp selenium` in venv | 08c1c91 |
| C3 Cache TTL vs polling | Critical | **FIXED** | 08c1c91 |
| C4 Circuit ordering | Critical | **FIXED** | ae4c83c |
| C5 Daily state reset | Critical | **FIXED** | ae4c83c |
| C6 Restart deadlock | Critical | **FIXED** | ae4c83c |
| C7 Shutdown liquidation | Critical | **FIXED** | ae4c83c |
| C8 Gap timing (yesterday's move) | Critical | OPEN — needs design decision (pre-open data source vs 09:15 rescan) | — |
| H1-H9 | High | OPEN | — |
| M1-M9 | Medium | OPEN | — |
| L1-L6 | Low | OPEN | — |
| S1-S3 | Security (Azure NSG/dashboard) | OPEN — infra change, not code | — |

---

## Run Modes

```bash
# Live trading (Mon-Fri, IST schedule)
python main.py

# Dry-run (one-shot pre-market pipeline on yesterday's data)
python main.py --dry-run

# Backtest
python backtest.py --start 2025-01-01 --end 2025-03-31 [--capital 100000]
```

---

*State initialized: 2026-06-05 | Completed: 2026-06-07*
