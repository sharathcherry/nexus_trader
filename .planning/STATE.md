---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: in-progress
last_updated: "2026-06-06T21:10:00.000Z"
progress:
  total_phases: 8
  completed_phases: 2
  total_plans: 15
  completed_plans: 4
  percent: 27
---

# STATE: nexus_trader

**Project:** nexus_trader — NSE India Intraday Paper Trading System
**Last updated:** 2026-06-06
**Updated by:** executor (Phase 2 complete)

---

## Project Reference

**Core Value:** A reliable daily paper trading pipeline that wakes up at 8:30 AM IST, runs without intervention through 3:30 PM, and produces a reviewed trade ledger — proving the strategy logic works before any real capital is risked.

**Current Focus:** Phase 3 — Paper Portfolio Engine

---

## Current Position

**Active Phase:** 3 — Paper Portfolio Engine
**Active Plan:** None (Phase 2 complete, Phase 3 not started)
**Phase Status:** Phase 2 complete
**Overall Status:** Data layer complete — MarketDataFetcher, Indicators, universe all live

```
Progress: [████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 27% (2/8 phases)
```

| Phase | Status |
|-------|--------|
| 1. Foundation | Complete |
| 2. Data Layer | Complete |
| 3. Paper Portfolio Engine | Not started |
| 4a. Pre-Market Agents | Not started |
| 4b. Market Session Agents | Not started |
| 4c. Post-Market Agent | Not started |
| 5. Orchestrator & Scheduler | Not started |
| 6. Dry-Run & Backtest | Not started |

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Phases complete | 2/8 |
| Requirements delivered | 20/57 (SCAF-01..05 + DATA-01..15) |
| Plans written | 15 |
| Plans complete | 4 |
| Blockers active | 0 |

---

## Accumulated Context

### Key Decisions Made

| Decision | Rationale | Phase |
|----------|-----------|-------|
| Use `google-genai>=2.0.0` not `google-generativeai` | `google-generativeai` deprecated/frozen November 2025; new SDK has different import pattern | 1 |
| Inline pandas Indicators, no `ta` library | `ta==0.11.0` has unfixed pandas 2.x bugs; VWAP/EMA/RSI/ATR/ORB implemented directly | 2 |
| SQLite WAL mode for position state | Single source of truth; survives process restart; WAL prevents read/write contention | 3 |
| Exchange charge rate: 0.0000307 not 0.0000335 | Corrected from PROJECT.md spec; ~9% overstatement in spec; Zerodha actual rate used | 3 |
| `BackgroundScheduler` not `BlockingScheduler` | BlockingScheduler prevents the main asyncio loop from running alongside scheduler | 5 |
| `await asyncio.sleep(60)` not `time.sleep(60)` | `time.sleep()` in async context blocks event loop; APScheduler 15:15 job cannot fire | 4b/5 |
| Force square-off dual safety | APScheduler `date` job AND loop time check both call idempotent `force_squareoff()` with `_squaredoff` guard | 4b |
| I0+I1 concurrent via `asyncio.gather`, I2->I3 sequential | I0 and I1 are independent; I2 needs I1 output; I3 needs I2 output | 4a |
| `watchlist_ready` asyncio.Event | Prevents 09:15 market-open job from firing while pre-market pipeline is still running | 4a/5 |
| Backtester last (Phase 6) | Strategy logic must be finalized before replay is meaningful; early backtest gives misleading results | 6 |
| 15-minute data delay documented from day one | yfinance NSE data is 15 min stale; must be in every trade record and I9 Claude reviewer prompt | 2 |
| `prepost=False` on all yfinance calls | Pre-open indicative candles (09:00-09:15) unreliable; use only confirmed session data | 2 |

### Critical Pitfalls Documented

1. `google-generativeai` is deprecated — all Gemini imports use `from google import genai`
2. yfinance NSE data is 15 minutes delayed — log at startup, embed in every trade record
3. Corporate actions create false gap signals — AgentI1 must filter ex-dividend/bonus/split dates
4. `ta` 0.11.0 pandas 2.x incompatibility — replaced with inline pandas implementations
5. `time.sleep(60)` blocks async event loop — use `await asyncio.sleep(60)` everywhere
6. `max_instances` not set causes job overlap — set on every APScheduler `add_job()` call
7. Exchange charge rate in PROJECT.md is incorrect (0.0000335 vs actual 0.0000307)
8. Gemini free-tier TPM budget reduced December 2025 — log token count from first call

### Todos (Active)

- [x] Phase 1 — Foundation complete (2026-06-06)
- [x] Phase 2 — Data Layer complete (2026-06-06)
- [ ] Verify corporate actions data source accessibility (nseindia.com vs nselib) before Phase 4a
- [ ] Compile hardcoded list of restructured Nifty 100 symbols with post-restructuring date caps before Phase 6

### Blockers

None active.

---

## Session Continuity

**To resume:** Run `/gsd:execute-phase 3` to begin Paper Portfolio Engine phase.

**Context for next session:**

- Phase 2 complete: data/universe.py (100 Nifty symbols), data/market_data.py (MarketDataFetcher), data/indicators.py (Indicators class with 6 @staticmethods), tests/ scaffold with 13/16 tests green
- Phase 1 complete: requirements.txt, config.py, utils/logger.py, folder scaffold, .env.example, .gitignore, main.py
- pybroker installed as lib-pybroker (correct PyPI package name)
- google-genai>=2.0.0 installed, google-generativeai absent from requirements.txt
- Config singleton at `from config import config` — all phases use this pattern
- Logger factory at `from utils.logger import setup_logger` — all phases use this pattern
- .env file must exist with 4 keys before any import of config

---

*State initialized: 2026-06-05*
