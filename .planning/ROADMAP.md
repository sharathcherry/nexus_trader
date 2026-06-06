# ROADMAP: nexus_trader

**Project:** nexus_trader — NSE India Intraday Paper Trading System
**Milestone:** v1 — Fully Automated Daily Pipeline
**Granularity:** Fine (8 focused phases)
**Created:** 2026-06-05
**Coverage:** 57/57 v1 requirements mapped

---

## Phases

- [ ] **Phase 1: Foundation** — Project scaffold, google-genai migration, config, .env, logger
- [ ] **Phase 2: Data Layer** — MarketDataFetcher (yfinance guards), inline pandas Indicators, NSE universe
- [ ] **Phase 3: Paper Portfolio Engine** — PaperPortfolio, OrderManager, Zerodha brokerage math, SQLite persistence
- [ ] **Phase 4a: Pre-Market Agents** — AgentI0 (global cues/Gemini), AgentI1 (gap screener), AgentI2 (news filter), AgentI3 (watchlist ranker)
- [ ] **Phase 4b: Market Session Agents** — AgentI4 (signal engine, 4 strategies), AgentI6 (position monitor/trailing SL)
- [ ] **Phase 4c: Post-Market Agent** — AgentI9 (Claude Sonnet reviewer, daily report, parameter advisory)
- [ ] **Phase 5: Orchestrator & Scheduler** — NexusTrader class, APScheduler IST, pre-market pipeline, market loop, ASCII banner
- [ ] **Phase 6: Dry-Run & Backtest** — --dry-run CLI mode, NexusBacktester, README

---

## Phase Details

### Phase 1: Foundation

**Goal**: Project is runnable with correct dependencies — google-genai SDK wired, config loaded from .env, structured logger active, no deprecated packages
**Depends on**: Nothing (first phase)
**Requirements**: SCAF-01, SCAF-02, SCAF-03, SCAF-04, SCAF-05
**Success Criteria** (what must be TRUE):

  1. `pip install -r requirements.txt` completes without error; `google-generativeai` is absent, `google-genai>=2.0.0` is present with correct version pin
  2. `python -c "from config import config; print(config.CAPITAL)"` prints 100000 without errors, reading GEMINI_API_KEY and ANTHROPIC_API_KEY from .env
  3. Running the logger utility emits INFO (green), WARNING (yellow), ERROR (red) lines to terminal and creates a dated log file in logs/
  4. `.env` is listed in `.gitignore`; `.env.example` documents all four required keys (GEMINI_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

**Plans**: TBD

### Phase 2: Data Layer

**Goal**: All market data and indicator computations are available, guarded, and tested with known inputs — the foundation every agent depends on
**Depends on**: Phase 1
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06, DATA-07, DATA-08, DATA-09, DATA-10, DATA-11, DATA-12, DATA-13, DATA-14, DATA-15
**Success Criteria** (what must be TRUE):

  1. `MarketDataFetcher` returns a correctly shaped OHLCV DataFrame for a known NSE symbol (e.g. RELIANCE.NS) and returns `None` / empty without raising on a bad symbol or network failure
  2. All seven global indices (S&P 500, NASDAQ, Nikkei, Hang Seng, Crude, Gold, USD/INR) are fetched and non-null on a market day; the 0.2s inter-call delay is observable in timing logs
  3. `Indicators.vwap()`, `.ema()`, `.rsi()`, `.atr()`, `.orb()`, `.volume_ratio()` all produce float outputs (no NaN) on a valid intraday DataFrame; VWAP resets at 09:15 IST daily
  4. NSE universe contains exactly 100 symbols, all ending in `.NS` with sector tags; no `ta` library imports remain anywhere in the data module

**Plans**: 3 plans
Plans:
**Wave 0**

- [ ] 02-00-PLAN.md — Test scaffold (tests/conftest.py + tests/test_data_layer.py, stubs for DATA-01 through DATA-15, all RED)

**Wave 1** *(blocked on Wave 0 completion)*

- [ ] 02-01-PLAN.md — NSE universe (data/universe.py) + MarketDataFetcher (data/market_data.py), DATA-01 through DATA-09
- [ ] 02-02-PLAN.md — Indicators class (data/indicators.py), DATA-10 through DATA-15

### Phase 3: Paper Portfolio Engine

**Goal**: Financial simulation core is correct and persistent — buy/sell/partial_exit/trailing SL execute with accurate Zerodha brokerage math and SQLite-backed state survives process restart
**Depends on**: Phase 1
**Requirements**: PORT-01, PORT-02, PORT-03, PORT-04, PORT-05, PORT-06, PORT-07, PORT-08, PORT-09, PORT-10, PORT-11, PORT-12, PORT-13
**Success Criteria** (what must be TRUE):

  1. A scripted buy of 10 shares at Rs 500 followed by sell at Rs 550 produces net P&L = gross profit minus exact Zerodha brokerage (min(Rs 20, 0.03% turnover) + STT 0.025% sell-side + exchange charges 0.0000307 + 18% GST on brokerage), matching a manual calculation to the rupee
  2. After 5 open positions, a 6th `buy()` call is rejected; after daily P&L crosses -2%, `is_halted` is set and all subsequent `buy()` calls are rejected until reset
  3. Portfolio state (positions, capital, daily P&L) written to SQLite survives a simulated process kill and is correctly restored on re-init
  4. `OrderManager.check_and_execute_exits()` closes all positions at 15:15 via force square-off; the exit is idempotent (calling it twice does not double-close)

**Plans**: TBD

### Phase 4a: Pre-Market Agents

**Goal**: The pre-market pipeline delivers a ranked watchlist of up to 10 NSE stocks by 09:00 IST — gap-filtered, news-clean, AI-biased, with rule-based fallbacks for all Gemini calls
**Depends on**: Phase 2, Phase 3
**Requirements**: AGNT-01, AGNT-02, AGNT-03, AGNT-04, AGNT-05, AGNT-06, AGNT-07, AGNT-08
**Success Criteria** (what must be TRUE):

  1. AgentI0 returns a structured result with `bias_strength`, `gift_nifty_gap_pct`, `valid_strategies`, `confidence`; when Gemini is unavailable, rule-based fallback returns NEUTRAL with `confidence=0.0` rather than raising
  2. AgentI1 on a day with known gap-up stocks returns only candidates with 1.5%-8.0% gap, prev volume >= 500k, price Rs 50-Rs 5,000; stocks with ex-dividend/bonus/split dates that day are excluded
  3. AgentI2 removes BLOCK_DEAL and INDEX_REBALANCE tagged gaps; the 1s delay between Gemini calls is verifiable in logs; UNKNOWN fallback is set on any API failure without stopping the pipeline
  4. AgentI3 watchlist contains 0-10 stocks, all with R:R >= 1.5, each carrying `entry_trigger`, `stop_loss`, `target`, and `strategy` fields; stocks below the R:R threshold are absent

**Plans**: TBD

### Phase 4b: Market Session Agents

**Goal**: During market hours, the signal engine detects valid entries using all four strategies and the position monitor enforces exits — the portfolio self-manages from 09:15 to 15:15 IST
**Depends on**: Phase 3, Phase 4a
**Requirements**: AGNT-09, AGNT-10, AGNT-11, AGNT-12
**Success Criteria** (what must be TRUE):

  1. AgentI4 runs a 60-second polling loop from 09:15 to 15:15; no entries are placed before 09:30 or after 14:00 — these gates are enforced at order submission, not at signal evaluation
  2. Each of the four strategies (GAP_AND_GO, GAP_FILL, ORB_BREAKOUT, VWAP_RECLAIM) triggers a buy on a crafted synthetic candle sequence that meets its documented entry conditions
  3. `force_squareoff_all()` at 15:15 closes all open positions exactly once (idempotent); subsequent calls produce no additional trades
  4. AgentI6 detects partial exit at 1:1 R:R, updates trailing SL per strategy rules, and flags `POSSIBLE_CIRCUIT` when price is unchanged for 3 consecutive polling cycles

**Plans**: 4 plans
Plans:
**Wave 1**

- [ ] 04B-01-PLAN.md — AgentI6 position monitor (circuit detection, hard exits, partial exit, trailing SL)
- [ ] 04B-02-PLAN.md — AgentI4 core infrastructure (__init__, batch fetch, ORB override, force_squareoff_all)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 04B-03-PLAN.md — AgentI4 async run() loop and four-strategy signal evaluation
- [ ] 04B-04-PLAN.md — pytest suites for AGNT-09 through AGNT-12, conftest.py fixtures

### Phase 4c: Post-Market Agent

**Goal**: After each trading session, Claude Sonnet produces a structured review of the day's trades with parameter advisory — and the review is saved even if the API call partially fails
**Depends on**: Phase 3, Phase 4b
**Requirements**: AGNT-13, AGNT-14, AGNT-15, AGNT-16
**Success Criteria** (what must be TRUE):

  1. AgentI9 calls Claude Sonnet with the full daily trade ledger and 20-day rolling stats; the prompt is capped at 10,000 tokens; streaming is used so a partial response is never silently lost
  2. Parsed Claude response contains `session_verdict`, winning/underperforming strategies, `parameter_adjustments`, and `tomorrow_watch` in structured Pydantic output
  3. Any Claude suggestion that raises MAX_OPEN_POSITIONS, lowers MIN_RISK_REWARD below 1.5, or raises RISK_PER_TRADE_PCT above 1.5% is auto-rejected with a log entry; the remaining valid suggestions are preserved
  4. Review JSON is saved to `logs/performance/review_YYYYMMDD.json`; on API failure a `review_failed_YYYYMMDD.json` sentinel is written; formatted tabulate summary prints to terminal in all cases

**Plans**: 2 plans
Plans:
**Wave 1**

- [ ] 04C-01-PLAN.md — Test scaffold (conftest.py + test_agent_i9.py, 10 test cases, all RED)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 04C-02-PLAN.md — AgentI9 full implementation (agents/agent_i9.py, makes all 10 tests GREEN)

### Phase 5: Orchestrator & Scheduler

**Goal**: The full daily pipeline runs unattended Mon-Fri on IST schedule — pre-market at 08:30, market session from 09:15, post-market at 15:35 — skipping NSE 2026 holidays with graceful interrupt handling
**Depends on**: Phase 4a, Phase 4b, Phase 4c
**Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05, ORCH-06, ORCH-07
**Success Criteria** (what must be TRUE):

  1. `python main.py` prints the NEXUS ASCII banner, starts APScheduler with IST timezone, and shows the pre-market pipeline executing at 08:30 IST; `max_instances=1` prevents job overlap when pre-market overruns
  2. Pre-market pipeline output includes a formatted watchlist table (symbol, gap%, strategy, R:R, catalyst) printed before 09:15; a NO_TRADE_DAY condition (holiday or zero-volume `^NSEI` check) aborts cleanly with a log message
  3. KeyboardInterrupt during market session triggers graceful shutdown — all open positions are force-closed, portfolio state is saved, and the process exits with code 0
  4. On an NSE 2026 holiday date, the scheduler skips all jobs and logs "NSE holiday — no trading today"; on a non-holiday weekday it runs the full pipeline end-to-end

**Plans**: TBD

### Phase 6: Dry-Run & Backtest

**Goal**: The pipeline can be validated on historical data before any live session is trusted, and a multi-month backtest produces strategy-level performance metrics
**Depends on**: Phase 5
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06, TEST-07
**Success Criteria** (what must be TRUE):

  1. `python main.py --dry-run` runs the full pre-market pipeline on yesterday's data, prints the watchlist table, and exits cleanly with no errors and no market loop started
  2. `python backtest.py --start 2025-01-01 --end 2025-03-31` processes 60+ trading days (skipping weekends and NSE holidays) and prints a formatted report without raising
  3. Backtest report contains all eight required metrics: `total_trades`, `win_rate`, `total_net_pnl`, `total_return_pct`, `sharpe_ratio`, `max_drawdown_pct`, `profit_factor`, `monthly_returns`
  4. README.md documents: installation steps, `.env` setup with API key sources, and all three run modes (`python main.py`, `python main.py --dry-run`, `python backtest.py`)

**Plans**: TBD

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/0 | Not started | - |
| 2. Data Layer | 0/3 | Planned | - |
| 3. Paper Portfolio Engine | 0/0 | Not started | - |
| 4a. Pre-Market Agents | 0/0 | Not started | - |
| 4b. Market Session Agents | 0/4 | Planned | - |
| 4c. Post-Market Agent | 0/2 | Planned | - |
| 5. Orchestrator & Scheduler | 0/0 | Not started | - |
| 6. Dry-Run & Backtest | 0/0 | Not started | - |

---

## Coverage Validation

| Phase | Requirements | Count |
|-------|-------------|-------|
| 1. Foundation | SCAF-01, SCAF-02, SCAF-03, SCAF-04, SCAF-05 | 5 |
| 2. Data Layer | DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, DATA-06, DATA-07, DATA-08, DATA-09, DATA-10, DATA-11, DATA-12, DATA-13, DATA-14, DATA-15 | 15 |
| 3. Paper Portfolio Engine | PORT-01, PORT-02, PORT-03, PORT-04, PORT-05, PORT-06, PORT-07, PORT-08, PORT-09, PORT-10, PORT-11, PORT-12, PORT-13 | 13 |
| 4a. Pre-Market Agents | AGNT-01, AGNT-02, AGNT-03, AGNT-04, AGNT-05, AGNT-06, AGNT-07, AGNT-08 | 8 |
| 4b. Market Session Agents | AGNT-09, AGNT-10, AGNT-11, AGNT-12 | 4 |
| 4c. Post-Market Agent | AGNT-13, AGNT-14, AGNT-15, AGNT-16 | 4 |
| 5. Orchestrator & Scheduler | ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05, ORCH-06, ORCH-07 | 7 |
| 6. Dry-Run & Backtest | TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06, TEST-07 | 7 |
| **TOTAL** | | **57/57** |

All 57 v1 requirements mapped. No orphans. Coverage: 100%.

---

## Research Flags (from SUMMARY.md)

- **Phase 4a (Gemini agents):** Gemini free-tier TPM budget was reduced December 2025. Log `response.usage_metadata.total_token_count` from the first Gemini call and monitor daily cumulative spend. Size I2 batch at max 20 stocks at 1 req/sec.
- **Phase 6 (Backtester):** NSE Bhavcopy cross-validation required. Maintain a hardcoded list of Nifty 100 symbols with corporate restructurings (mergers/demergers 2022-2025) and cap their lookback dates accordingly. Verify before trusting backtest results.

---

*Roadmap created: 2026-06-05*
*Last updated: 2026-06-06 after Phase 4C planning*
