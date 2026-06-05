# Research Summary: nexus_trader

**Project:** nexus_trader -- NSE India intraday paper trading system
**Domain:** Automated intraday paper trading (Python, Nifty 100, gap strategies)
**Researched:** 2026-06-05
**Confidence:** HIGH (stack, architecture, brokerage math), MEDIUM (yfinance NSE behavior, gap thresholds)

---

## Executive Summary

nexus_trader is a single-process, fully automated paper trading pipeline for NSE India intraday gap strategies. It runs a pre-market AI-assisted watchlist pipeline at 08:30 IST, a 60-second polling market session loop from 09:15 to 15:15, and a Claude Sonnet post-market review at 15:35. The correct implementation model is asyncio throughout -- I/O-bound HTTP calls to yfinance, Gemini, and Anthropic make threading unnecessary and harmful. APScheduler (BackgroundScheduler, not BlockingScheduler) drives phase transitions with IST timezone explicit on every trigger.

Two hard blockers must be resolved before any code is written. First, the project spec lists `google-generativeai` as the Gemini SDK -- this package was frozen in November 2025 and is now deprecated. All Gemini code must use `google-genai` (the unified SDK) with a different import pattern and client instantiation. Second, the `ta` 0.11.0 library has unfixed pandas 2.x compatibility issues; the four indicators nexus_trader actually needs (VWAP, EMA, RSI, ATR) should be implemented as inline pandas functions rather than depending on the broken upstream library, starting in Phase 2.

The four gap strategies (GAP_AND_GO, GAP_FILL, ORB_BREAKOUT, VWAP_RECLAIM) are all well-established in Indian market literature and the PROJECT.md thresholds (1.5%-8.0% gap, 500k volume, Rs 50-Rs 5,000 price) are correctly calibrated. The brokerage math is accurate with one minor exception: the exchange charge rate should be 0.0000307 (not 0.0000335 as specified) -- a conservative 9% overstatement acceptable for simulation until Phase 3. yfinance provides NSE data with a 15-minute delay; this is a hard simulation limitation that must be documented in every trade record from day one and disclosed in the I9 Claude reviewer prompt.

---

## Key Findings

### Recommended Stack

The stack is almost entirely correct as specified. The single breaking change is the Gemini SDK: replace `google-generativeai` with `google-genai>=2.0.0` everywhere. Use `gemini-2.0-flash` as the default model (configurable in `config.py`). The new import pattern is `from google import genai; client = genai.Client(api_key=...)`. All other stack choices are sound.

**Core technologies:**

- `yfinance==0.2.40` -- NSE OHLCV data; pinned for API stability. All symbols require `.NS` suffix in ALL CAPS. Wrap every call; returns empty DataFrames silently on failure and on rate-limit (HTTP 429).
- `APScheduler==3.11.2` -- Cron scheduling in IST. Use `BackgroundScheduler` with `max_instances=1` and `timezone=pytz.timezone("Asia/Kolkata")` on every `add_job()` call. `BlockingScheduler` prevents the main loop from running.
- `google-genai>=2.0.0` -- Replaces deprecated `google-generativeai`. Use `GenerateContentConfig(response_mime_type="application/json", response_schema=PydanticModel)` for structured output. Free tier: 15 RPM. Process max 20 stocks at 1 req/sec in I2; build deterministic fallback alongside primary path.
- `anthropic>=0.28.0` -- Claude Sonnet post-market reviewer (I9 only, once daily). Use `client.messages.parse(output_format=PydanticModel)`. Set `timeout=120`; use streaming so partial review is never lost.
- `ta==0.11.0` -- Has unfixed pandas 2.x bugs (positional indexing, FutureWarning in trend.py). Pin `pandas>=2.0.0,<3.0.0` for Phase 1. Replace with inline pandas implementations of VWAP/EMA/RSI/ATR in Phase 2 and drop the dependency.
- `pandas>=2.0.0,<3.0.0`, `numpy>=1.24.0`, `pytz>=2024.1` -- Data processing and timezone. pytz required by APScheduler; do not mix pytz-aware and zoneinfo-aware datetimes.
- `colorlog>=6.7.0`, `tabulate>=0.9.0` -- Terminal output. Use `tablefmt="grid"` (ASCII) for log files on Windows; `rounded_outline` for terminal display.

**Remove from requirements.txt:** `google-generativeai` (deprecated November 2025).

### Expected Features

**Must have (table stakes) -- all confirmed by research:**

- Gap scanner: `(open - prev_close) / prev_close`, filter 1.5%-8.0%, volume >= 500k, price Rs 50-Rs 5,000
- Corporate actions filter: cross-reference ex-dividend/bonus/split dates against gap list -- false gaps are indistinguishable without this; must be built in I1 alongside the screener, not deferred
- VWAP (session-anchored, resets at 09:15 daily), EMA 9/21, RSI 14, ATR 14, ORB high/low from 09:15-09:30
- Position sizing: `quantity = floor(risk_amount / (entry - stop_loss))` with 1% risk rule on Rs 1,00,000 capital
- Brokerage math: `min(20, turnover * 0.0003)` brokerage + STT 0.00025 sell-side + exchange charges 0.0000307 + GST 18% on brokerage
- Force square-off at 15:15 IST -- dual safety: APScheduler `date` job + loop time check, both calling an idempotent `force_squareoff()` with `_squaredoff` guard
- Time gates: no entries before 09:30, no entries after 14:00 -- guard enforced at point of order submission, not at signal evaluation
- 2% daily loss halt, max 5 concurrent positions, max 15 trades/day
- SQLite with WAL mode for position state persistence; JSON daily ledger export for Claude reviewer
- NSE 2026 holiday list + zero-volume abort check on `^NSEI` at 08:30 as dual guard

**Should have (differentiators):**

- `WORST_CANDLE` fill model for stop-losses -- simulates gap-through; exact fill for stops overstates performance
- Slippage column in trade ledger (signal price vs. fill price) -- log from day one, analyze later
- `POSSIBLE_CIRCUIT` flag when price unchanged for 3 consecutive 60-second polls
- Strategy-level P&L breakdown (GAP_AND_GO / GAP_FILL / ORB_BREAKOUT / VWAP_RECLAIM separately)
- Dry-run mode replaying yesterday's data with `--dry-run` CLI flag
- `watchlist_ready` asyncio.Event gate so the 09:15 market-open job waits if pre-market is still running
- 15-minute data delay notice embedded in every trade record and in the I9 Claude reviewer prompt

**Defer to v2+:**

- Trailing stop partial-exit (add after basic fixed stops work reliably)
- NexusBacktester (requires finalized signal logic)
- Time-of-day performance bucketing
- Stamp duty and SEBI charges in brokerage math (combined under Rs 3 per trade)

### Architecture Approach

Single-process asyncio pipeline. Three daily phases fire via APScheduler: pre-market (08:30), market session loop (09:15-15:15 with `await asyncio.sleep(60)` -- never `time.sleep()`), and post-market (15:35). Pre-market runs I0 and I1 concurrently via `asyncio.gather(return_exceptions=True)`, then I2 and I3 sequentially. SQLite with WAL mode is the single source of truth for position state; agents re-initialize from DB each day.

**Major components:**

1. `data/MarketDataFetcher` -- three-layer guard on every yfinance call: catch exception, check `df.empty`, validate timezone. Returns `None` on failure; all callers handle `None` explicitly. Sequential bulk fetch with `await asyncio.sleep(0.2)` between calls -- never gather 100 symbols simultaneously.
2. `data/Indicators` -- VWAP/EMA/RSI/ATR/ORB from OHLCV. Phase 1: uses `ta` with `pandas<3.0.0` pin. Phase 2: replaced with inline pandas implementations, `ta` dependency dropped.
3. `execution/PaperPortfolio` + `execution/OrderManager` -- position state, brokerage math, 1% risk sizing, fill models. SQLite-backed. Time guard on `buy()` at order submission point.
4. `agents/i0` through `agents/i9` -- thin wrappers around data and AI calls. I0+I1 concurrent; I2->I3 sequential. All Gemini agents require a deterministic rule-based fallback built in parallel with the primary path.
5. `utils/scheduler.py` -- BackgroundScheduler, IST, `max_instances=1`, `coalesce=True` on all jobs. Force-squareoff registered as `date` trigger at session open.
6. `main.py / NexusTrader` -- phase router, `_squaredoff` flag, top-level exception handler.

### Critical Pitfalls

1. **`google-generativeai` is deprecated (frozen Nov 2025)** -- Replace with `google-genai`. Changes all Gemini import and instantiation patterns. Must be corrected in Phase 1 before any Gemini code is written.

2. **yfinance 15-minute data delay for NSE** -- All intraday prices are up to 15 minutes stale. Log `exchangeDataDelayedBy=15` at startup; embed delay notice in every trade record; disclose in I9 Claude reviewer prompt. Fundamental simulation constraint, not fixable.

3. **False gap signals from corporate actions** -- yfinance `auto_adjust=True` adjusts historical closes retroactively but today's intraday open is raw, creating phantom gaps on ex-dividend/bonus/split dates. Corporate actions filter must be built in I1 alongside the gap screener, not deferred.

4. **`ta` 0.11.0 pandas 2.x incompatibility** -- Open GitHub issues, no upstream fix. Pin `pandas<3.0.0` for Phase 1. Replace with inline pandas VWAP/EMA/RSI/ATR implementations in Phase 2.

5. **`time.sleep(60)` in polling loop blocks the entire event loop** -- APScheduler cannot fire the 15:15 square-off job. Use `await asyncio.sleep(60)`. No `time.sleep()` in any `async def`.

6. **`max_instances` not set on APScheduler jobs** -- Pre-market pipeline can still be running when the 09:15 job fires, causing a race condition on watchlist state. Set `max_instances=1` on every job and use a `watchlist_ready` event.

7. **Exchange charge rate in PROJECT.md is 0.0000335, actual Zerodha rate is 0.0000307** -- Minor conservative overstatement (~9%). Correct in Phase 3 implementation.

---

## Implications for Roadmap

### Phase 1: Foundation and Data Layer

**Rationale:** Nothing else is reliable without validated data. Gap screener, signal engine, and AI agents all depend on `MarketDataFetcher` and `Indicators` being correct. The `google-genai` migration must happen here before any Gemini code is written anywhere in the project.

**Delivers:** Project scaffold, corrected requirements.txt (with `google-genai`, `pandas<3.0.0`), `MarketDataFetcher` with three-layer guards and exponential backoff, inline pandas Indicators (VWAP/EMA/RSI/ATR/ORB), NSE universe with .NS suffix, `config.py`, `utils/logger.py`, IST datetime utilities, 15-minute delay logging at startup.

**Addresses:** All four strategy indicator prerequisites, NSE symbol format, bulk fetch rate-limit protection.

**Avoids:** C1 (data delay documented upfront), C3 (empty DataFrame guards first), C4 (rate-limit backoff), google-generativeai deprecation blocker.

**Research flag:** Standard patterns -- no additional research needed.

---

### Phase 2: Paper Portfolio Engine and Brokerage Math

**Rationale:** The financial simulation core must be tested with known inputs before any strategy runs. Fill models must be decided now -- changing them later invalidates all prior paper results.

**Delivers:** `PaperPortfolio` (buy/sell/partial_exit, `_squaredoff` guard, `WORST_CANDLE` fill model for stops), `OrderManager` (1% risk sizing, 5-position gate, 2% daily loss halt, 14:00 order-submission time guard), SQLite WAL persistence, JSON daily ledger schema with slippage column from day one.

**Addresses:** Position sizing, brokerage math (corrected exchange rate 0.0000307), force square-off idempotency, trade ledger schema.

**Avoids:** M2 (fill model decided before data collection), Mi4 (14:00 guard at order submission not at signal evaluation).

**Research flag:** Standard patterns -- no additional research needed.

---

### Phase 3: Gap Screener and Pre-Market AI Pipeline (I1, I0, I2, I3)

**Rationale:** Gap screener is the entry point for all signals. Corporate actions filter must be built here, not deferred. AI agents use corrected `google-genai` SDK. Deterministic fallback for each Gemini agent must be built in parallel with the primary path.

**Delivers:** I1 gap screener with corporate actions filter, I0 global cues agent (Gemini), I2 news filter (Gemini, max 20 stocks at 1 req/sec), I3 watchlist ranker with rule-based fallback, `asyncio.gather(return_exceptions=True)` for concurrent I0+I1, sequential I2->I3, `watchlist_ready` asyncio.Event.

**Addresses:** Gap filter (1.5%-8.0%, 500k vol, Rs 50-Rs 5,000), corporate actions ex-date filtering, global market bias, news-driven gap suppression, watchlist ranking.

**Avoids:** C2 (corporate actions filter built here), M4 (Gemini rate limit + deterministic fallback), M6 (watchlist_ready event prevents 09:15 race), M1 (no live intraday fetch before 09:15).

**Research flag:** Gemini free-tier TPM budget was reduced December 2025. Monitor `response.usage_metadata.total_token_count` and log cumulative daily token spend from first call.

---

### Phase 4: Signal Engine, Position Monitor, Scheduler, Orchestrator (I4, I6, APScheduler)

**Rationale:** Signal engine and position monitor require the full data and execution stack to exist first. APScheduler wiring can only be tested when all components it orchestrates are real. Build strategy order: GAP_AND_GO (simplest) -> GAP_FILL -> ORB_BREAKOUT -> VWAP_RECLAIM (most indicator-dependent).

**Delivers:** I4 signal engine with 09:30 entry gate, 14:00 order-submission cutoff, all four strategy implementations. I6 position monitor with trailing SL and `POSSIBLE_CIRCUIT` detection. APScheduler BackgroundScheduler with `max_instances=1` and IST on every trigger, dual-safety force square-off (APScheduler date job + loop time check), NSE holiday list + zero-volume `^NSEI` abort check, NexusTrader orchestrator.

**Addresses:** All four strategies, market session loop with `await asyncio.sleep(60)`, force square-off idempotency, scheduler timezone correctness.

**Avoids:** time.sleep() in async context, Mi1 (IST explicit on all triggers), M6 (max_instances=1), Mi3 (zero-volume abort check).

**Research flag:** VWAP_RECLAIM confirmation timing may need tuning after first live paper runs -- monitor per-strategy P&L in early sessions.

---

### Phase 5: Post-Market Review, Metrics, and Dry-Run Mode (I9, Performance, CLI)

**Rationale:** Claude reviewer requires a completed real trade ledger. Performance metrics are only meaningful after live paper sessions. Dry-run mode validates the full pipeline on historical data before any live session is trusted.

**Delivers:** I9 Claude Sonnet reviewer (Pydantic structured output, `timeout=120`, streaming, prompt capped at 10,000 tokens, sentinel file `review_failed_YYYYMMDD.json` on failure), daily performance metrics (win rate, profit factor, avg R, max drawdown, strategy breakdown, slippage analysis), `--dry-run` CLI flag, structured terminal output with colorlog + tabulate.

**Avoids:** M5 (120s timeout + streaming + prompt size guard).

**Research flag:** Standard patterns -- no additional research needed.

---

### Phase 6: Backtester (NexusBacktester)

**Rationale:** Backtester must come last -- strategy logic must be finalized before replay is meaningful. Requires hardcoded list of stocks with unreliable yfinance history due to corporate restructurings.

**Delivers:** NexusBacktester replaying historical OHLCV through I1->I4 strategy logic, per-strategy backtest results, fill model comparison, hardcoded "unreliable history" symbol list with post-restructuring date caps.

**Avoids:** M3 (cap lookback for restructured stocks; cross-validate against NSE Bhavcopy archives).

**Research flag:** Current list of structurally changed Nifty 100 symbols (mergers/demergers in last 3 years) needs manual verification before backtester results are relied upon.

---

### Phase Ordering Rationale

- Data before everything: a silent empty DataFrame bug in Phase 1 becomes a mysterious NaN cascade in Phase 4.
- Brokerage math before strategies: incorrect cost simulation contaminates all downstream metrics. Test with known inputs before any strategy runs.
- GAP_AND_GO first, VWAP_RECLAIM last: simplest signal to most indicator-dependent. Establishes a working baseline before adding complexity.
- AI agents after rule-based core: without a deterministic baseline, you cannot distinguish an AI bug from a data bug.
- I9 after live sessions: Claude reviewer is meaningless on synthetic trade data.
- Backtester last: replay on unfinished signal logic generates misleading results.

---

### Research Flags

Phases needing deeper research during planning:
- **Phase 3 (Gemini agents):** Free-tier TPM budget reduced December 2025 without documentation. Monitor token spend from first call and plan batch sizes conservatively.
- **Phase 6 (Backtester):** NSE Bhavcopy cross-validation and current list of structurally changed Nifty 100 symbols need manual verification before backtester results are trusted.

Phases with standard patterns (no additional research needed):
- **Phase 1:** SQLite WAL, inline pandas indicators, yfinance retry guards.
- **Phase 2:** PaperPortfolio state machine, Zerodha brokerage math.
- **Phase 5:** Claude structured output, colorlog + tabulate.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All libraries verified against official docs and PyPI. google-genai migration path confirmed from official Google AI migration guide. ta issues confirmed from open GitHub issues. |
| Features | HIGH | Brokerage math verified against Zerodha official charges page 2026-06-05. Strategy thresholds confirmed across multiple Indian broker knowledge bases. |
| Architecture | HIGH | asyncio patterns from official docs. SQLite WAL from official SQLite docs. APScheduler behavior from official 3.x userguide. |
| Pitfalls | MEDIUM-HIGH | yfinance 15-min delay confirmed from NSE delayed data tariff document. Corporate actions false gap confirmed from yfinance GitHub issues. Rate limit behavior from GitHub issues (no official Yahoo documentation). Claude TTFT range is LOW confidence -- single source. |

**Overall confidence:** HIGH for implementation decisions; MEDIUM for yfinance edge-case behavior under production conditions.

### Gaps to Address

- **yfinance pre-open behavior (09:00-09:15):** Whether indicative candles appear in 1m data should be verified empirically on day one. Use `prepost=False` as defensive default throughout.
- **Gemini free-tier TPM budget:** Log `response.usage_metadata.total_token_count` from the first Gemini call and monitor cumulative daily spend.
- **NSE 2026 holiday list completeness:** Zero-volume abort check on `^NSEI` at 08:30 is the operational fallback for ad-hoc holidays not in the static list. Update static list each quarter.
- **Corporate actions data source for I1:** Confirm `nseindia.com/companies-listing/corporate-filings-actions` is programmatically accessible, or plan to use `nselib` corporate actions coverage, before Phase 3 implementation.

---

## Sources

### Primary (HIGH confidence)
- Zerodha official charges page -- brokerage, STT, exchange charge rates verified 2026-06-05
- APScheduler 3.x official userguide -- BackgroundScheduler, CronTrigger, misfire, coalesce
- Google AI Gemini migration docs -- google-genai SDK, structured output, GenerateContentConfig
- Anthropic platform docs -- structured outputs, client.messages.parse(), Pydantic pattern
- SQLite official docs -- WAL mode, PRAGMA journal_mode, busy_timeout
- Official asyncio Python docs -- gather, sleep, cooperative scheduling semantics

### Secondary (MEDIUM confidence)
- yfinance GitHub issues (#2612, #2125, #2393, #1531) -- NSE timezone bug, rate limit behavior, corporate actions adjustment, empty DataFrame patterns
- NSE delayed data tariff document (NSE archives) -- 15-minute delay for free-tier confirmed
- APScheduler GitHub issues (#346, #370) -- Windows timezone interaction, job overlap
- Indian broker knowledge bases (ICICI Direct, Groww, Samco, Angel One) -- strategy validation, gap thresholds

### Tertiary (LOW confidence)
- Community reports on Yahoo Finance rate limiting -- no official threshold published
- Claude TTFT latency range (3-15s) -- GitHub issues, not Anthropic official docs
- Gemini TPM free-tier post-December 2025 quota reduction -- community reports, not official documentation

---

*Research completed: 2026-06-05*
*Ready for roadmap: yes*
