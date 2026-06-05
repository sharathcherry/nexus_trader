# Architecture Patterns: nexus_trader

**Domain:** Automated intraday paper trading system (NSE India)
**Researched:** 2026-06-05
**Confidence:** HIGH (asyncio/APScheduler patterns), MEDIUM (yfinance NSE quirks), HIGH (SQLite persistence)

---

## Recommended Architecture

nexus_trader is a single-process, event-loop-driven pipeline. It is I/O-bound throughout — all waiting is on HTTP (yfinance, Gemini, Claude). This makes asyncio the correct concurrency model. No threading, no multiprocessing.

The process has three sequential phases per trading day, each with a distinct execution model:

```
08:30  Pre-market pipeline (concurrent async tasks, runs once, ~5–10 min)
         |
09:15  Market session loop (60-second polling, runs until 15:15)
         |
15:30  Post-market review (single async call to Claude Sonnet, runs once)
```

APScheduler (AsyncIOScheduler) fires phase transitions. The event loop runs continuously; APScheduler jobs are coroutines scheduled into it.

---

## Component Boundaries

| Component | Layer | Responsibility | Depends On |
|-----------|-------|----------------|------------|
| `main.py / NexusTrader` | Orchestrator | Phase sequencing, top-level error handling, APScheduler management | All layers |
| `agents/i0_global_cues.py` | Agent | Fetch SGX Nifty, Dow futures, VIX via Gemini Flash; return market bias score | data/, Gemini API |
| `agents/i1_gap_screener.py` | Agent | Screen Nifty 100 for 1.5%–8% overnight gaps, apply volume/price filters | data/MarketDataFetcher |
| `agents/i2_news_filter.py` | Agent | Filter watchlist for adverse news via Gemini Flash; drop flagged symbols | data/, Gemini API |
| `agents/i3_watchlist_ranker.py` | Agent | Score and rank remaining candidates by gap quality, sector, ATR | data/Indicators |
| `agents/i4_signal_engine.py` | Agent | Per-tick: check VWAP/EMA/RSI/ORB breakout signals on ranked watchlist | data/MarketDataFetcher, data/Indicators |
| `agents/i6_position_monitor.py` | Agent | Per-tick: evaluate trailing SL, partial exits, P&L on open positions | execution/PaperPortfolio |
| `agents/i9_reviewer.py` | Agent | Post-market: send trade ledger to Claude Sonnet, persist review narrative | execution/PaperPortfolio, Claude API |
| `execution/PaperPortfolio` | Execution | In-memory position state, Zerodha brokerage math, P&L calculation | utils/logger |
| `execution/OrderManager` | Execution | Position sizing (1% risk rule), entry validation, max-5-position gate | execution/PaperPortfolio |
| `data/MarketDataFetcher` | Data | yfinance wrappers with retry/empty-DataFrame guards, 0.2s inter-call delay | yfinance |
| `data/Indicators` | Data | VWAP, EMA, RSI, ATR, ORB computed from raw OHLCV | pandas, ta |
| `data/nse_universe.py` | Data | Hardcoded list of 100 Nifty symbols with .NS suffix and sector tags | — |
| `utils/scheduler.py` | Utils | APScheduler AsyncIOScheduler, IST timezone, holiday-aware weekday check | APScheduler, pytz |
| `utils/logger.py` | Utils | colorlog terminal handler + rotating file handler | colorlog |
| `utils/alerts.py` | Utils | Console/log summary output (no external push in v1) | utils/logger |

---

## Data Flow Diagram (Text)

```
                        ┌─────────────────────────────────────┐
                        │         APScheduler (IST)           │
                        │  cron: 08:30 / 09:15 / 15:15 / 15:30│
                        └───────────────┬─────────────────────┘
                                        │ fires coroutines
                                        ▼
                        ┌─────────────────────────────────────┐
                        │        NexusTrader (main.py)        │
                        │   Phase router + top-level handler  │
                        └──┬──────────────────────────────┬───┘
                           │                              │
          ┌────────────────▼────────────┐    ┌───────────▼──────────────┐
          │   PRE-MARKET PIPELINE       │    │   MARKET SESSION LOOP     │
          │   asyncio.gather() →        │    │   while True + 60s sleep  │
          │                             │    │                           │
          │  I0 ──► global_bias (score) │    │  every tick:              │
          │  I1 ──► raw_watchlist       │    │  ┌──────────────────────┐ │
          │         (gap-filtered)      │    │  │ MarketDataFetcher    │ │
          │  I2 ──► news_filtered_list  │    │  │ fetch 100 symbols    │ │
          │  I3 ──► ranked_watchlist    │    │  │ (batched, 0.2s delay)│ │
          │         (top N candidates)  │    │  └──────────┬───────────┘ │
          └────────────────┬────────────┘    │             │             │
                           │                 │             ▼             │
                           │ passes          │  ┌──────────────────────┐ │
                           │ ranked_watchlist│  │ Indicators           │ │
                           │ to session loop │  │ VWAP/EMA/RSI/ATR/ORB│ │
                           │                 │  └──────────┬───────────┘ │
                           │                 │             │             │
                           │                 │       ┌─────┴──────┐      │
                           │                 │       ▼            ▼      │
                           │                 │  I4 Signal    I6 Monitor  │
                           │                 │  Engine       (positions) │
                           │                 │       │            │      │
                           │                 │       ▼            ▼      │
                           │                 │  OrderManager  PaperPort  │
                           │                 │  (size, gate)  (SL/P&L)  │
                           │                 └────────────────────┬──────┘
                           │                                      │
                           │                                      ▼
                           │                         ┌────────────────────┐
                           └────────────────────────►│  SQLite (state.db) │
                                                     │  + JSON (ledger)   │
                                                     └────────────┬───────┘
                                                                  │
                                                     ┌────────────▼───────┐
                                                     │  POST-MARKET       │
                                                     │  I9 Reviewer       │
                                                     │  Claude Sonnet     │
                                                     │  → review.txt      │
                                                     └────────────────────┘
```

---

## Answer 1: Polling Loop Design — Use asyncio, Not Threading or sleep()

**Verdict: AsyncIOScheduler + async polling loop. No `time.sleep()`, no threads.**

Rationale: The system is exclusively I/O-bound (yfinance HTTP calls, Gemini API, Claude API). `asyncio` cooperative multitasking is the correct model because:

- `time.sleep(60)` in a `while True` loop blocks the entire thread. During that 60 seconds nothing else can run — no APScheduler heartbeat, no signal processing, no misfire detection.
- `threading` introduces OS-level context switching overhead, requires locks around shared portfolio state, and adds accidental parallelism risk. Determinism is more valuable than parallelism here.
- `await asyncio.sleep(60)` yields control back to the event loop during the wait, allowing APScheduler to fire the 15:15 square-off job on time, even mid-loop-iteration.

**Correct polling loop pattern:**

```python
async def market_session_loop(self):
    IST = pytz.timezone("Asia/Kolkata")
    while True:
        now = datetime.now(IST)

        # 15:15 hard stop — session loop exits, APScheduler job fires separately
        if now.time() >= time(15, 15):
            break

        await self._run_tick()          # I4 + I6 agents
        await asyncio.sleep(60)         # yields to event loop; APScheduler stays alive
```

The `await asyncio.sleep(60)` is non-blocking. APScheduler's 15:15 job fires correctly even while the loop is "sleeping."

Confidence: HIGH (verified against asyncio cooperative scheduling semantics and trading bot literature from Feb 2026)

---

## Answer 2: Paper Portfolio Persistence — SQLite with WAL Mode

**Verdict: SQLite for state, JSON for human-readable daily ledger export.**

| Need | Solution | Reason |
|------|----------|--------|
| Intraday position state (open trades, cash balance) | SQLite (in-memory → flush on change) | ACID transactions, survives crash, queryable |
| Daily trade ledger (closed trades, P&L summary) | JSON file (one per day) | Human-readable, easy to pass to Claude reviewer |
| Long-term performance history | SQLite (trades table) | Queryable across days for backtester |

**SQLite setup (one-time on DB creation):**

```python
con.execute("PRAGMA journal_mode=WAL")   # readers never block writer
con.execute("PRAGMA busy_timeout=5000")  # retry 5s on lock contention
```

WAL mode lets the monitoring loop read positions while the order writer commits simultaneously without lock contention. Persistent across restarts — WAL mode is stored in the file header.

**Why not JSON-only:** JSON has no atomic writes. If the process crashes mid-write you get a corrupt file. No queries possible for backtester. No crash recovery.

**Why not PostgreSQL:** Gross overkill for a single-process system. Zero additional infrastructure required for SQLite.

**File layout:**

```
data/
  state.db          ← SQLite: positions, orders, daily_stats tables
  ledger/
    2026-06-05.json ← Daily closed trade export (human-readable)
    2026-06-05_review.txt ← Claude Sonnet narrative output
```

Confidence: HIGH (SQLite WAL characteristics verified from official SQLite docs + community sources)

---

## Answer 3: Time Gate "No New Entries After 14:00" — Check in Signal Engine

**Verdict: Check `datetime.now(IST).time() >= time(14, 0)` inside I4 signal engine. Do not add a separate APScheduler job for this.**

The entry gate is a signal filter, not a scheduling event. The correct location is inside I4 signal engine's `should_enter()` method:

```python
def should_enter(self, symbol: str, signal: dict) -> bool:
    IST = pytz.timezone("Asia/Kolkata")
    now = datetime.now(IST)

    # No new entries before 09:30 (opening noise window)
    if now.time() < time(9, 30):
        return False

    # No new entries after 14:00
    if now.time() >= time(14, 0):
        return False

    # ... remaining R:R, risk, position count checks
    return True
```

This is the correct design because:
- The rule is a pre-condition on entry decisions, not a state transition
- It composes cleanly with the other entry filters (R:R >= 1.5, max 5 positions, 2% daily loss halt)
- Adding an APScheduler job to set a flag introduces shared mutable state and async ordering complexity
- The 60-second loop naturally polls this check; if the loop is mid-sleep at 14:00 the next tick (at most 60s later) will see the gate closed

**No entries in the first 15 minutes (before 09:30)** follows the identical pattern with the lower time bound. Both gates live in `i4_signal_engine.py`.

Confidence: HIGH (pattern consistent across multiple trading bot implementations reviewed)

---

## Answer 4: Pre-Market Pipeline — Concurrent Where Independent, Sequential Where Dependent

**Verdict: Concurrent `asyncio.gather()` for I0+I1 (both are independent data fetches), then sequential awaits for I2→I3 (each depends on prior output).**

The dependency graph:

```
I0 (global cues)    I1 (gap screener)
      \                   /
       \                 /
        asyncio.gather()         ← runs both concurrently (~same time)
              |
              ▼
          I2 (news filter)       ← sequential: needs I1 output
              |
              ▼
          I3 (ranker)            ← sequential: needs I2 output + I0 bias score
              |
              ▼
         ranked_watchlist        ← passed into market session loop
```

**Implementation:**

```python
async def pre_market_pipeline(self) -> list[str]:
    # I0 and I1 are independent — run concurrently
    global_bias, raw_watchlist = await asyncio.gather(
        self.i0.run(),
        self.i1.run(),
        return_exceptions=True          # don't let one failure kill both
    )

    # Handle gather exceptions before proceeding
    if isinstance(global_bias, Exception):
        logger.warning(f"I0 failed: {global_bias}; defaulting to neutral bias")
        global_bias = 0.0
    if isinstance(raw_watchlist, Exception):
        logger.error(f"I1 failed: {raw_watchlist}; aborting pre-market")
        return []

    # I2 requires raw_watchlist; sequential
    news_filtered = await self.i2.run(raw_watchlist)

    # I3 requires news_filtered + global_bias; sequential
    ranked = await self.i3.run(news_filtered, global_bias)
    return ranked
```

`return_exceptions=True` is critical. Without it, if I0 (Gemini Flash call) throws a network error, `asyncio.gather()` cancels I1 as well. With it, both run to completion and you handle failures per-agent.

The total pre-market runtime shrinks from (I0_time + I1_time + I2_time + I3_time) to (max(I0_time, I1_time) + I2_time + I3_time). Typically I0 and I1 are both 2–5 second API calls, so you save ~2–5 minutes in a window where every minute matters (must complete before 09:15).

Confidence: HIGH (asyncio.gather documentation + multi-agent trading architecture sources)

---

## Answer 5: yfinance Empty/None Error Handling

**Verdict: Three-layer guard. Never trust a raw yfinance return.**

yfinance has two distinct failure modes for NSE symbols:
1. **Silent empty DataFrame**: `history()` returns an empty DataFrame with no exception. This is the most dangerous — naive code proceeds to compute indicators on zero rows and produces NaN cascades.
2. **YFRateLimitError (HTTP 429)**: Raised as an exception since yfinance ~0.2.40. Requires exponential backoff retry.

**Canonical fetch wrapper for `MarketDataFetcher`:**

```python
import yfinance as yf
import time
import logging
from pandas import DataFrame

logger = logging.getLogger(__name__)

def fetch_history(
    symbol: str,
    period: str = "5d",
    interval: str = "1m",
    max_retries: int = 3,
) -> DataFrame | None:
    """
    Fetch OHLCV history for an NSE symbol.
    Returns None on permanent failure; caller must handle None explicitly.
    """
    delay = 1.0
    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            # Guard 1: Empty DataFrame (silent failure)
            if df is None or df.empty:
                logger.warning(f"{symbol}: empty DataFrame (attempt {attempt+1})")
                time.sleep(delay)
                delay *= 2
                continue

            # Guard 2: Timezone sanity — every valid NSE ticker has a timezone
            if ticker.fast_info.get("timezone") is None:
                logger.warning(f"{symbol}: missing timezone, likely invalid symbol")
                return None  # Don't retry; symbol is bad

            return df

        except Exception as exc:
            # Covers YFRateLimitError, network errors, datetime/str arithmetic bug (#2612)
            logger.warning(f"{symbol}: exception on attempt {attempt+1}: {exc}")
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"{symbol}: all retries exhausted")
                return None

    return None
```

**Caller contract:** every agent and indicator that calls `MarketDataFetcher` must check for `None` before any DataFrame operation. Never call `.iloc[0]`, `.max()`, or indicator functions on an unvalidated return.

**Bulk fetch pattern** (screener fetching 100 symbols):

```python
async def fetch_universe(self, symbols: list[str]) -> dict[str, DataFrame]:
    results = {}
    for sym in symbols:
        df = fetch_history(sym)          # sync; already has retry
        if df is not None:
            results[sym] = df
        await asyncio.sleep(0.2)         # mandatory inter-call delay (rate limit)
    return results
```

Do not `asyncio.gather()` 100 yfinance calls simultaneously — Yahoo Finance will 429 the entire batch. Sequential with 0.2s delay is the correct rate-limit-respecting pattern. The 100-symbol scan takes ~20 seconds, well within the pre-market window.

Confidence: MEDIUM-HIGH (empty DataFrame behavior confirmed from yfinance GitHub issues #359, #2612; timezone guard from discussion #1555; exponential backoff from issues #2125, #2422)

---

## Answer 6: Force Square-Off at 15:15 — Dual Safety Pattern

**Verdict: Use BOTH an APScheduler date job AND a loop time check. Each is a safety net for the other.**

Neither approach alone is fully reliable:
- APScheduler's `date` trigger can misfire if the process is under load, if the thread pool is exhausted, or if `misfire_grace_time` is too tight.
- A loop time check fires only at the next loop iteration — up to 60 seconds late.

The dual-safety pattern:

```python
# In utils/scheduler.py — register at session start (09:15)
def register_squareoff_job(scheduler, nexus_trader, trade_date):
    IST = pytz.timezone("Asia/Kolkata")
    squareoff_dt = IST.localize(
        datetime.combine(trade_date, time(15, 15))
    )
    scheduler.add_job(
        nexus_trader.force_squareoff,
        trigger="date",
        run_date=squareoff_dt,
        misfire_grace_time=120,         # fire up to 2 min late if delayed
        coalesce=True,                  # never run twice if multiple misfires
        id="force_squareoff",
        replace_existing=True,
    )

# In market_session_loop — secondary check
async def market_session_loop(self):
    IST = pytz.timezone("Asia/Kolkata")
    squaredoff = False
    while True:
        now = datetime.now(IST)
        if now.time() >= time(15, 15) and not squaredoff:
            await self.force_squareoff()
            squaredoff = True
            break
        await self._run_tick()
        await asyncio.sleep(60)

# force_squareoff must be idempotent
async def force_squareoff(self):
    if self._squaredoff:               # guard against double-call
        return
    self._squaredoff = True
    logger.info("Force square-off triggered at 15:15")
    await self.portfolio.close_all_positions(reason="eod_squareoff")
```

`_squaredoff` flag makes `force_squareoff()` idempotent — calling it twice (once from APScheduler, once from the loop) produces no side effects.

`misfire_grace_time=120` means: if the job was supposed to fire at 15:15 but the process was busy, fire it anyway if we're within 2 minutes. `coalesce=True` prevents it from firing multiple times if several misfires queued.

Confidence: HIGH (APScheduler misfire/coalesce semantics from official 3.x docs; idempotency pattern is standard defensive programming)

---

## Build Order (Suggested)

Build in dependency order — never stub a layer that is actively called by a higher layer.

| Phase | Components | Why This Order |
|-------|-----------|----------------|
| 1 | `config.py`, `utils/logger.py`, `data/nse_universe.py` | Everything else imports these; zero dependencies |
| 2 | `data/MarketDataFetcher` (with retry/guard pattern) | All agents depend on this; test it in isolation first |
| 3 | `data/Indicators` (VWAP, EMA, RSI, ATR, ORB) | Depends only on pandas/ta and DataFetcher output |
| 4 | `execution/PaperPortfolio`, `execution/OrderManager` | Core state machine; test brokerage math here |
| 5 | `agents/i1_gap_screener.py` | First agent; pure data layer consumer |
| 6 | `agents/i0_global_cues.py`, `agents/i2_news_filter.py` | Both use Gemini API; add together |
| 7 | `agents/i3_watchlist_ranker.py` | Consumes I0+I1+I2 output |
| 8 | `agents/i4_signal_engine.py`, `agents/i6_position_monitor.py` | Tick-level agents; need full data + execution layer |
| 9 | `agents/i9_reviewer.py` | Claude API call; needs completed trade ledger |
| 10 | `utils/scheduler.py`, `main.py / NexusTrader` | Orchestration; all components must exist first |
| 11 | Dry-run mode (`--dry-run` flag) | Wires everything together on historical data |
| 12 | Backtester (`NexusBacktester`) | Last: needs proven signal logic to replay |

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Blocking Sleep in Async Context
**What:** `time.sleep(60)` inside an `async def`
**Why bad:** Blocks the entire event loop thread. APScheduler cannot fire. 15:15 job misfires.
**Instead:** `await asyncio.sleep(60)`

### Anti-Pattern 2: Unchecked DataFrame Operations
**What:** `df["Close"].iloc[-1]` immediately after `ticker.history()`
**Why bad:** yfinance returns empty DataFrames silently for valid NSE symbols (rate limits, timezone bugs)
**Instead:** `if df is None or df.empty: return None` before any operation

### Anti-Pattern 3: Concurrent Bulk yfinance Fetch
**What:** `asyncio.gather(*[fetch(s) for s in 100_symbols])`
**Why bad:** Yahoo Finance 429s the entire batch; all futures fail together
**Instead:** Sequential loop with `await asyncio.sleep(0.2)` between calls

### Anti-Pattern 4: APScheduler-Only Square-Off
**What:** Relying solely on an APScheduler date job for the 15:15 cutoff
**Why bad:** A misfire (pool exhausted, process load spike) causes positions to remain open past 15:30
**Instead:** Dual-safety: APScheduler job + loop time check + idempotent `force_squareoff()`

### Anti-Pattern 5: Mutable Agent State Between Days
**What:** Keeping I4 or I6 signal state in Python instance variables between trading days
**Why bad:** Stale state from prior day contaminates next day's signals
**Instead:** SQLite is the source of truth; agents re-initialize from DB on each day's startup

### Anti-Pattern 6: Synchronous AI API Calls in the Polling Tick
**What:** Calling Gemini Flash inside `_run_tick()` every 60 seconds
**Why bad:** At ₹0.01/call × 360 ticks × 100 symbols = unnecessary cost and latency in the critical path
**Instead:** Gemini Flash is pre-market only (I0, I2). Tick-level signal generation (I4) uses deterministic rule-based indicators only.

---

## Scalability Considerations

This system is intentionally not scalable beyond single-process. That is correct for v1.

| Concern | Current (v1) | If Needed Later |
|---------|--------------|-----------------|
| Symbol universe | 100 Nifty stocks | Move to async fetch with rate-limit-aware batching |
| Multiple strategies | Single pipeline | Separate agents into independent processes with IPC |
| Data latency | 60s yfinance polling | Replace with WebSocket feed (Zerodha Kite Ticker) |
| State concurrency | Single async process | SQLite WAL handles read/write concurrency adequately |

---

## Sources

- asyncio vs threading for trading systems: https://medium.com/@trademamba/asyncio-for-algorithmic-trading-part-1-93327929aef6
- asyncio.gather() concurrent execution: https://www.pythontutorial.net/python-concurrency/python-asyncio-gather/
- APScheduler 3.x userguide (misfire, coalesce, date trigger): https://apscheduler.readthedocs.io/en/3.x/userguide.html
- yfinance empty DataFrame / NSE symbols: https://github.com/ranaroussi/yfinance/issues/2612
- yfinance timezone guard heuristic: https://github.com/ranaroussi/yfinance/discussions/1555
- yfinance rate limit / exponential backoff: https://github.com/ranaroussi/yfinance/issues/2125
- SQLite WAL mode concurrent reads: https://sqlite.org/wal.html
- SQLite WAL Python setup: https://dev.to/lumin-playstar/sqlite-wal-mode-10x-performance-for-python-apps-4ic
- Multi-agent trading architecture: https://medium.com/@ishveen/building-a-multi-agent-ai-trading-system-technical-deep-dive-into-architecture-b5ba216e70f3
