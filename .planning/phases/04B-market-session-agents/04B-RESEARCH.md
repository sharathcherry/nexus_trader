# Phase 4B: Market Session Agents - Research

**Researched:** 2026-06-06
**Domain:** Python asyncio polling loop, yfinance batch download, PaperPortfolio integration, intraday signal engine
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Pure price trigger signal conditions per strategy (no indicator confirmations):
  - `GAP_AND_GO`: `current_price >= entry_trigger`
  - `ORB_BREAKOUT`: `current_price >= entry_trigger`
  - `VWAP_RECLAIM`: `current_price >= entry_trigger`
  - `GAP_FILL`: `current_price <= entry_trigger`
- **D-02:** ORB_BREAKOUT entry_trigger override: at 09:30, AgentI4 calls `Indicators.orb(df, n=2)` and updates each ORB_BREAKOUT WatchlistEntry's `entry_trigger = orb_high`. One-time per session.
- **D-03:** Each signal fires at most once per symbol per session. Buy placed → remove from active candidates. Already-open position for same symbol → skip.
- **D-04:** Time gates enforced at buy submission only (not signal evaluation). `if current_time < 09:30 or current_time > 14:00: skip_buy()`.
- **D-05:** AgentI6 called at START of each polling cycle before entry checks. Single public method: `monitor_positions(portfolio, watchlist_map, current_prices, current_time)`.
- **D-06:** `watchlist_map` is `dict[str, WatchlistEntry]` passed from AgentI4. AgentI6 reads `stop_loss`, `target`, `strategy`, `atr` per position.
- **D-07:** Phase 5 imports AgentI4 only. AgentI6 is instantiated inside AgentI4 as `self.monitor = AgentI6()`.
- **D-08:** AgentI6 tracks last 3 prices per position in `dict[str, deque]` (maxlen=3). All 3 identical → POSSIBLE_CIRCUIT.
- **D-09:** On POSSIBLE_CIRCUIT: log WARNING, add to `self.circuit_set`, skip all checks for that symbol all remaining cycles.
- **D-10:** `circuit_set` lives in AgentI4 (entry gate) AND AgentI6 (exit skip). AgentI4 passes reference on each call.
- **D-11:** Partial exit at 1:1 R:R for `GAP_AND_GO` and `ORB_BREAKOUT` only. `current_price >= entry_price + (entry_price - stop_loss)` → `portfolio.partial_exit(symbol, 0.5)`. Trailing SL activates after partial exit.
- **D-12:** `GAP_FILL` and `VWAP_RECLAIM` hold for full target — no partial exit.
- **D-13:** Trailing SL for `GAP_AND_GO`: trail at `current_price - 0.75 * atr` once `current_price >= entry_price + atr`. SL only moves up.
- **D-14:** Trailing SL for `ORB_BREAKOUT`: move SL to breakeven (`entry_price`) when 1:1 R:R hit. No further trailing.
- **D-15:** `GAP_FILL` and `VWAP_RECLAIM` have fixed SL throughout session.
- **D-16:** `async def run(watchlist, portfolio, watchlist_ready_event)` — waits for `watchlist_ready.wait()`, then `while True: await asyncio.sleep(60); if current_time > 15:15: break; cycle()`.
- **D-17:** `force_squareoff_all()` idempotent via `self._squaredoff = False` guard. Checks flag first, sets to True, then closes positions.
- **D-18:** Each cycle: batch yfinance download for ALL watchlist symbols at once. 0.2s sleep before batch fetch.

### Claude's Discretion

- Exact log messages for each trade action (buy, partial exit, SL hit, target hit)
- Whether AgentI4 prints a live positions table each cycle (tabulate)
- Deque import internals

### Deferred Ideas (OUT OF SCOPE)

- RSI/volume confirmation overlays for signal quality
- Re-entry logic after partial exit
- Live positions table printed each cycle (Claude's discretion)

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AGNT-09 | AgentI4 runs signal detection loop from 9:15 AM to 3:15 PM, polling every 60 seconds | Asyncio `while True` loop with `await asyncio.sleep(60)`, IST time comparison via pytz, loop breaks at 15:15 |
| AGNT-10 | AgentI4 gates entries: no new entries before 9:30 AM or after 14:00; checks strategy-specific conditions using live indicators | Time gate at buy submission via `current_time.hour/minute` comparison; four signal conditions documented in D-01 |
| AGNT-11 | AgentI4.force_squareoff_all() closes all open positions at market price at 15:15 IST | `_squaredoff` guard pattern verified working; calls `portfolio.sell()` for each open position |
| AGNT-12 | AgentI6 monitors open positions each cycle: partial exit at 1:1 R:R, trailing stop updates, hard SL/target checks, POSSIBLE_CIRCUIT detection | All exit math verified; deque circuit detection confirmed; portfolio method integration mapped |

</phase_requirements>

---

## Summary

Phase 4B implements two agents: `AgentI4` (signal engine, `agents/agent_i4.py`) and `AgentI6` (position monitor, `agents/agent_i6.py`). AgentI4 runs an `async def run()` loop from 09:15 to 15:15 IST, polling every 60 seconds using `await asyncio.sleep(60)`. Each cycle: batch-fetches intraday candles for all watchlist symbols via `yf.download()` with MultiIndex output, runs AgentI6 first for position monitoring, then checks each watchlist candidate for entry signals. AgentI6 is a stateful class (deque price tracking) instantiated once inside AgentI4.

The critical implementation subtleties are: (1) `yf.download()` returns flat `Index` for single-symbol input but `MultiIndex` for 2+ symbols — the code must handle both cases; (2) missing symbols in batch download return empty DataFrames from `.xs()` rather than raising KeyError; (3) ORB override fires once at 09:30 using a `_orb_set` boolean guard; (4) `entry_price` for exit math comes from `portfolio.get_portfolio_summary()['positions']`, NOT from `WatchlistEntry.entry_trigger`; (5) force square-off idempotency uses `_squaredoff` flag in AgentI4, not in PaperPortfolio — this is AgentI4's own guard.

The test strategy relies on synthetic candle DataFrames injected in place of live yfinance data — no live market access required. pytest 9.0.2 is available. All verification was done against the running environment (Python 3.12.10, yfinance 0.2.40, pandas 2.3.3, pytz 2024.x, Windows ProactorEventLoop).

**Primary recommendation:** Implement AgentI6 as a pure synchronous class (no async) called from AgentI4 each cycle. Keep all yfinance I/O in AgentI4. Structure the cycle as: fetch → monitor (AgentI6) → entries → log.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Signal detection (4 strategies) | AgentI4 (signal engine) | Indicators (data layer) | Pure price comparison against WatchlistEntry.entry_trigger; no AI involvement |
| Position monitoring, trailing SL, partial exit | AgentI6 (position monitor) | PaperPortfolio (execution) | Stateful per-position logic; calls portfolio mutation methods |
| Circuit breaker detection | AgentI6 (deque tracking) | AgentI4 (entry gate via circuit_set) | AgentI6 owns deque state; both agents share circuit_set reference |
| ORB high override | AgentI4 (one-time at 09:30) | Indicators.orb() (data layer) | Timing logic belongs in AgentI4; ORB calculation delegated to data layer |
| Order execution, position state, brokerage | PaperPortfolio / OrderManager (execution) | — | Financial state is execution layer's responsibility; agents only call buy/sell/partial_exit |
| Time-gating entry window | AgentI4 (buy submission guard) | config.py (constants) | Enforced at submission per D-04; signal evaluation still runs outside window |
| Batch market data fetch | AgentI4 (per cycle) | MarketDataFetcher / yfinance | One batch per cycle for all watchlist symbols; 0.2s rate-limit sleep before fetch |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| yfinance | 0.2.40 (pinned) | Intraday 5m OHLCV via batch download | Sole data source; version pinned in requirements.txt |
| asyncio | stdlib | Polling loop with non-blocking sleep | Already used in Phase 4a; `await asyncio.sleep(60)` keeps event loop free for APScheduler |
| pytz | >=2024.1 | IST timezone for time gate comparisons | Verified working on Windows ProactorEventLoop |
| collections.deque | stdlib | Circuit detection rolling window (maxlen=3) | O(1) append/rotate; maxlen auto-evicts oldest |
| pandas | >=2.0,<3.0 | DataFrame operations on OHLCV | Already installed; MultiIndex handling documented |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tabulate | >=0.9 | Optional live positions table per cycle | Claude's discretion — useful for debugging |
| colorlog | >=6.7 | Colored trade action log output | Per-trade logging (BUY/SELL/SL HIT/TARGET) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncio.sleep(60) | APScheduler CronTrigger | APScheduler polling is Phase 5's job; agents own their own loop timing |
| deque(maxlen=3) | list with manual trim | deque is O(1) append/pop, handles maxlen automatically |
| yf.download() batch | N individual Ticker.history() calls | Batch is one request vs N; 60-second cycle budget permits it |

**No new packages required.** All imports are stdlib or already in requirements.txt.

---

## Package Legitimacy Audit

No new packages are installed in this phase. All dependencies (yfinance, asyncio, pytz, collections, pandas, tabulate, colorlog) are either stdlib or already pinned in requirements.txt from prior phases.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
  Phase 5 Orchestrator
         |
         | passes: List[WatchlistEntry], PaperPortfolio, watchlist_ready_event
         v
  +---------------------+
  |     AgentI4.run()   |  <-- awaits watchlist_ready.wait() first
  |  async polling loop |
  +---------------------+
         |
         | every 60s (await asyncio.sleep(60))
         v
  +---------- CYCLE START ----------+
  |                                  |
  | 1. time.sleep(0.2)              |
  | 2. yf.download(symbols_list)    |  <-- batch fetch: all watchlist symbols
  |    → MultiIndex DataFrame       |
  |                                  |
  | 3. AgentI6.monitor_positions()  |  <-- called FIRST, before entry checks
  |    per open position:           |
  |    - circuit check (deque)      |
  |    - hard SL/target exit        |
  |    - partial exit at 1:1 R:R    |
  |    - trailing SL update         |
  |    calls: portfolio.sell()      |
  |           portfolio.partial_exit|
  |           portfolio.update_sl() |
  |                                  |
  | 4. Entry checks (per watchlist) |
  |    - skip if in circuit_set     |
  |    - skip if already bought     |
  |    - evaluate signal condition  |
  |    - if signal + time gate OK:  |
  |      portfolio.buy()            |
  |      remove from candidates     |
  |                                  |
  | 5. ORB override (once at 09:30) |
  |    if not _orb_set and           |
  |       current_time >= 09:30:    |
  |      Indicators.orb(df, n=3)    |
  |      update entry_trigger       |
  |      _orb_set = True            |
  +----------------------------------+
         |
         | current_time > 15:15 → break loop
         v
  force_squareoff_all(current_prices)
  (_squaredoff guard: idempotent)
         |
         | returns to Phase 5
         v
  AgentI4c (Phase 4c) reads daily report
```

### Recommended Project Structure
```
agents/
├── __init__.py
├── models.py           # WatchlistEntry, GapCandidate, MarketBias (from Phase 4a)
├── agent_i0.py         # Phase 4a (exists)
├── agent_i1.py         # Phase 4a (exists)
├── agent_i2.py         # Phase 4a (exists)
├── agent_i3.py         # Phase 4a (exists)
├── agent_i4.py         # THIS PHASE — signal engine
└── agent_i6.py         # THIS PHASE — position monitor
```

### Pattern 1: Asyncio Polling Loop with IST Time Gate

**What:** `async def run()` loops with `await asyncio.sleep(60)`, breaking when IST time exceeds 15:15.
**When to use:** Any agent that polls on a fixed interval without blocking the event loop.

```python
# Source: STATE.md "Key Decisions Made" + verified in env (Python 3.12 Windows ProactorEventLoop)
import asyncio
import pytz
import datetime

IST = pytz.timezone("Asia/Kolkata")

async def run(self, watchlist, portfolio, watchlist_ready_event):
    await watchlist_ready_event.wait()  # blocks until pre-market pipeline done
    while True:
        await asyncio.sleep(60)
        current_time = datetime.datetime.now(IST)
        if current_time >= current_time.replace(hour=15, minute=15, second=0, microsecond=0):
            break
        await self._cycle(portfolio, current_time)
    self.force_squareoff_all(portfolio, current_prices={})
```

**Critical:** `await asyncio.sleep(60)` must come BEFORE the `if current_time > 15:15` check per D-16.

### Pattern 2: yfinance Batch Download with MultiIndex Extraction

**What:** `yf.download(list_of_symbols)` returns MultiIndex columns when len >= 2, flat Index when len == 1.
**When to use:** Every polling cycle in AgentI4 to fetch all watchlist symbols in one request.

```python
# Source: VERIFIED against yfinance 0.2.40 running in this environment
import time
import yfinance as yf
import pandas as pd

def _fetch_batch(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Returns {symbol: ohlcv_df}. Empty df if symbol has no data."""
    time.sleep(0.2)  # rate-limit guard (DATA-09)
    if not symbols:
        return {}

    raw = yf.download(
        symbols,
        period="1d",
        interval="5m",
        prepost=False,       # exclude pre-open indicative candles (locked: STATE.md)
        auto_adjust=False,   # raw prices (locked: CLAUDE.md)
        progress=False,
    )

    if raw.empty:
        return {s: pd.DataFrame() for s in symbols}

    result = {}
    if len(symbols) == 1:
        # Single-symbol download returns flat Index, not MultiIndex
        result[symbols[0]] = raw
    else:
        # Multi-symbol returns MultiIndex: level 0 = field, level 1 = symbol
        for sym in symbols:
            try:
                sym_df = raw.xs(sym, axis=1, level=1)
                result[sym] = sym_df  # may be empty if yfinance had no data for sym
            except KeyError:
                result[sym] = pd.DataFrame()  # symbol absent from response

    return result
```

**Key finding — VERIFIED:** Missing symbols in multi-symbol download do NOT raise `KeyError` from `.xs()` in yfinance 0.2.40 — they return an empty DataFrame (verified by running `yf.download(['RELIANCE.NS', 'FAKESYMBOL.NS'], ...)` and confirming `FAKESYMBOL.NS` appears in level-1 with shape `(0, 6)`). Callers should check `if df.empty` before using.

**Key finding — VERIFIED:** Single-symbol `yf.download(['RELIANCE.NS'], ...)` returns a flat `Index` (not `MultiIndex`). The `.xs()` call WILL FAIL with a single-symbol list. The `len(symbols) == 1` branch is mandatory.

### Pattern 3: Deque-Based Circuit Detection

**What:** Track last 3 prices per open position. Identical triplet = circuit (price freeze).
**When to use:** AgentI6.monitor_positions() — per open position, every cycle.

```python
# Source: collections stdlib; pattern verified in environment
from collections import deque

class AgentI6:
    def __init__(self):
        self._price_history: dict[str, deque] = {}  # symbol -> deque(maxlen=3)
        # circuit_set is passed in from AgentI4 on each call (D-10)

    def _check_circuit(self, symbol: str, current_price: float,
                        circuit_set: set) -> bool:
        """Returns True if circuit detected (price frozen for 3 cycles)."""
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=3)
        self._price_history[symbol].append(current_price)
        d = self._price_history[symbol]
        if len(d) == 3 and len(set(d)) == 1:
            circuit_set.add(symbol)
            return True
        return False
```

**Verified:** `deque(maxlen=3)` with three identical values: `len(set(deque)) == 1` correctly returns `True`. Normal price movement `[1500.0, 1502.0, 1501.0]` correctly returns `False`.

### Pattern 4: IST Time Comparisons with pytz

**What:** Get current IST time and compare against session boundary datetimes.
**When to use:** Time gates (09:30, 14:00, 15:15) and ORB override (09:30).

```python
# Source: VERIFIED against pytz in project environment (Windows, Python 3.12)
import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def _get_ist_time() -> datetime.datetime:
    return datetime.datetime.now(IST)

def _make_ist_boundary(hour: int, minute: int) -> datetime.datetime:
    """Create today's boundary time in IST."""
    now = datetime.datetime.now(IST)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

# Usage in cycle:
current_time = _get_ist_time()
entry_start   = _make_ist_boundary(9, 30)
entry_cutoff  = _make_ist_boundary(14, 0)
session_end   = _make_ist_boundary(15, 15)
orb_threshold = _make_ist_boundary(9, 30)

can_buy = entry_start <= current_time <= entry_cutoff
loop_done = current_time >= session_end
do_orb_override = current_time >= orb_threshold and not self._orb_set
```

**Verified:** `datetime.datetime.now(IST)` returns a timezone-aware datetime. `.replace()` on a timezone-aware datetime preserves the timezone — comparison between two IST-aware datetimes works correctly without any UTC conversion.

**Pitfall:** `datetime.datetime.now()` (no tz) is timezone-naive. Comparing a naive datetime against a pytz-aware datetime raises `TypeError: can't compare offset-naive and offset-aware datetimes`. Always use `datetime.datetime.now(IST)`.

### Pattern 5: Force Square-Off Idempotency

**What:** `_squaredoff` flag prevents double-close when called by both the loop-end and APScheduler backup job.
**When to use:** AgentI4.force_squareoff_all() — single call protection.

```python
# Source: STATE.md "Key Decisions Made" + 03-CONTEXT.md D-14; verified in environment
def force_squareoff_all(self, portfolio, current_prices: dict[str, float]) -> None:
    if self._squaredoff:
        logger.info("force_squareoff_all: already executed — skipping")
        return
    self._squaredoff = True
    summary = portfolio.get_portfolio_summary()
    for position in summary.get("positions", []):
        sym = position["symbol"]
        price = current_prices.get(sym, position["entry_price"])  # fallback to entry
        portfolio.sell(sym, price, reason="FORCE_SQUAREOFF")
    logger.info("force_squareoff_all: all positions closed")
```

**Note:** `_squaredoff` lives in AgentI4 (not PaperPortfolio). PaperPortfolio has its own `force_squaredoff` meta flag (03-CONTEXT D-14) which tracks the portfolio-level state. AgentI4's `_squaredoff` prevents AgentI4 from calling `portfolio.sell()` twice. Both layers having independent guards is intentional (STATE.md "force square-off dual safety").

### Pattern 6: ORB Override — One-Time at 09:30

**What:** Replace placeholder `entry_trigger` in ORB_BREAKOUT entries with the actual ORB high from 5-minute candles.
**When to use:** AgentI4 cycle, exactly once, when `current_time >= 09:30 AND not _orb_set`.

```python
# Source: 04B-CONTEXT D-02, 04A-CONTEXT D-11, 02-CONTEXT D-06
def _maybe_apply_orb_override(self, candles_map: dict, current_time) -> None:
    """
    At 09:30 (first cycle at/after 09:30), update ORB_BREAKOUT entry_triggers
    with actual ORB high from first 3 five-minute candles (09:15, 09:20, 09:25).
    """
    orb_threshold = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
    if self._orb_set or current_time < orb_threshold:
        return
    self._orb_set = True

    for sym, entry in self.watchlist_map.items():
        if entry.strategy != "ORB_BREAKOUT":
            continue
        df = candles_map.get(sym, pd.DataFrame())
        if df.empty or len(df) < 3:
            continue  # not enough candles yet — keep placeholder
        # First 3 rows = first 15 minutes (09:15, 09:20, 09:25 candles)
        orb_high, _ = Indicators.orb(df, n=3)
        if orb_high and orb_high > 0:
            entry.entry_trigger = orb_high
            logger.info(f"ORB override {sym}: entry_trigger → {orb_high:.2f}")
```

**Note on n parameter:** 04B-CONTEXT D-02 states `n=2` but 02-CONTEXT D-06 specifies `n_minutes=config.ORB_MINUTES` (15 minutes). With 5-minute candles, 15 minutes = 3 candles (09:15, 09:20, 09:25). The D-02 description "after 2 candles: 09:15 + 09:30" is misleading — at 09:30 there are 3 completed 5-minute candles. **Use `n=3` (candles) or `n_minutes=15` depending on how Phase 2 implemented `Indicators.orb()`.** The planner should verify Phase 2's actual `Indicators.orb()` signature before coding. See Open Questions #1.

### Pattern 7: Per-Cycle Error Isolation

**What:** Catch all exceptions inside the cycle body. The polling loop must never crash permanently from a single bad cycle (network error, malformed data).
**When to use:** Top of every cycle execution in AgentI4.

```python
# Source: asyncio best-practice; verified in environment
async def _run_cycle(self, portfolio, current_time):
    try:
        candles_map = self._fetch_batch(list(self.watchlist_map.keys()))
        self.monitor.monitor_positions(
            portfolio, self.watchlist_map, candles_map, current_time, self.circuit_set
        )
        self._check_entries(candles_map, portfolio, current_time)
        self._maybe_apply_orb_override(candles_map, current_time)
    except Exception as e:
        # Log and continue — one bad cycle must not kill the session
        logger.error(f"Cycle error (continuing): {e}", exc_info=True)
```

### Anti-Patterns to Avoid

- **`time.sleep(60)` in async context:** Blocks the ProactorEventLoop; APScheduler 15:15 job cannot fire. Always `await asyncio.sleep(60)`. [VERIFIED: STATE.md critical pitfall #5]
- **Single-symbol `.xs()` call:** `yf.download(['RELIANCE.NS'], ...)` returns flat Index; `.xs('RELIANCE.NS', axis=1, level=1)` will raise `TypeError`. Guard with `len(symbols) == 1` branch. [VERIFIED: live test]
- **Using `entry_trigger` as `entry_price` for exit math:** `WatchlistEntry.entry_trigger` is the signal threshold; actual fill price is `portfolio.get_portfolio_summary()['positions'][i]['entry_price']`. Trailing SL and partial exit require the actual fill price.
- **Comparing naive vs aware datetimes:** `datetime.datetime.now()` without tz vs `datetime.datetime.now(IST)` will raise `TypeError`. Use `datetime.datetime.now(IST)` everywhere. [VERIFIED]
- **Calling `force_squareoff_all()` without guard:** Without `_squaredoff` flag, APScheduler job AND loop-end both firing closes positions twice. [VERIFIED via STATE.md]
- **Mutating WatchlistEntry inside circuit_set loop:** After adding a symbol to `circuit_set`, continuing to evaluate it in the same cycle causes double-processing. Skip immediately after circuit detection.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rolling window of last N values | Custom list with manual index tracking | `collections.deque(maxlen=3)` | deque auto-evicts oldest; O(1) operations; thread-safe for single-thread async |
| Rate-limit retry logic | Exponential backoff loop | `time.sleep(0.2)` before batch fetch + empty DataFrame check | yfinance 429 returns empty DataFrame silently; 60-second poll interval is well within limits |
| IST time zone handling | UTC offset math | `pytz.timezone("Asia/Kolkata")` | Handles DST edge cases (India has no DST but pytz is the standard) |
| Brokerage math in exits | Re-implementing Zerodha formula | `portfolio.sell(symbol, price, reason)` | PaperPortfolio handles all brokerage math; do not re-implement |
| Position quantity tracking | Separate counter | `portfolio.get_portfolio_summary()['positions']` | SQLite-backed state; survives restart; single source of truth |

**Key insight:** All financial mutations belong in PaperPortfolio. AgentI4/I6 are pure signal engines — they observe prices and call portfolio methods; they never compute or store financial state.

---

## PaperPortfolio Integration Map

This is the complete call sequence AgentI4/I6 execute each cycle against PaperPortfolio. Understanding this prevents integration errors at coding time.

### AgentI4 buy() call sequence

```python
# Before calling buy():
# 1. Verify symbol NOT already in open positions (skip re-entry: D-03)
# 2. Verify time gate: entry_start <= current_time <= entry_cutoff (D-04)
# 3. Verify symbol NOT in circuit_set (D-09)
# 4. Verify signal condition met (D-01)
# 5. Calculate quantity via OrderManager.calculate_quantity()
#    (uses config.RISK_PER_TRADE_PCT / (entry_trigger - stop_loss))

success = portfolio.buy(
    symbol=sym,
    price=current_price,          # actual fill price (not entry_trigger)
    qty=qty,
    stop_loss=entry.stop_loss,
    target=entry.target,
    strategy=entry.strategy,
)
if success:
    del self.watchlist_map[sym]   # remove from active candidates (D-03)
```

### AgentI6 monitor_positions() call sequence per position

```python
# portfolio.get_portfolio_summary() returns:
# {
#   "capital": float,
#   "positions": [{"symbol", "entry_price", "qty", "stop_loss", "target",
#                  "strategy", "entry_time", "partial_exited"}, ...],
#   "daily_pnl": float,
#   "is_halted": bool,
#   "trade_count": int
# }

for pos in portfolio.get_portfolio_summary()["positions"]:
    sym = pos["symbol"]
    entry_price = pos["entry_price"]       # actual fill, NOT entry_trigger
    current_sl   = pos["stop_loss"]        # current (may have been updated by trailing)
    target       = pos["target"]
    strategy     = pos["strategy"]
    partial_done = pos["partial_exited"]   # bool — whether 50% already exited
    entry_obj    = watchlist_map.get(sym)  # for atr, original stop_loss
    atr          = entry_obj.atr if entry_obj else None

    price = current_prices.get(sym)
    if price is None or price == 0:
        continue

    # 1. Circuit check
    if self._check_circuit(sym, price, circuit_set):
        logger.warning(f"POSSIBLE_CIRCUIT {sym} — skipping for session")
        continue
    if sym in circuit_set:
        continue

    # 2. Hard exits (SL or target)
    if price <= current_sl:
        portfolio.sell(sym, price, reason="SL_HIT")
        continue
    if price >= target:
        portfolio.sell(sym, price, reason="TARGET_HIT")
        continue

    # 3. Partial exit at 1:1 R:R (GAP_AND_GO and ORB_BREAKOUT only)
    risk = entry_price - entry_obj.stop_loss  # original risk
    if not partial_done and strategy in ("GAP_AND_GO", "ORB_BREAKOUT"):
        if price >= entry_price + risk:
            portfolio.partial_exit(sym, 0.5)

    # 4. Trailing SL
    if strategy == "GAP_AND_GO" and atr and price >= entry_price + atr:
        new_sl = price - 0.75 * atr
        if new_sl > current_sl:                # SL only moves up
            portfolio.update_stop_loss(sym, new_sl)
    elif strategy == "ORB_BREAKOUT" and not partial_done:
        pass  # ORB SL moves to breakeven — handled with partial exit above
    elif strategy == "ORB_BREAKOUT" and partial_done:
        # After partial exit, SL should be at breakeven (entry_price)
        if entry_price > current_sl:
            portfolio.update_stop_loss(sym, entry_price)
```

**Methods called:**
- `portfolio.get_portfolio_summary()` — read positions [VERIFIED: 03-CONTEXT D-01, D-05]
- `portfolio.sell(symbol, price, reason)` — full exit on SL/target/squareoff [VERIFIED: 03-CONTEXT]
- `portfolio.partial_exit(symbol, 0.5)` — 50% exit at 1:1 R:R [VERIFIED: PORT-05, 03-CONTEXT]
- `portfolio.update_stop_loss(symbol, new_sl)` — trailing SL update [VERIFIED: PORT-06, 03-CONTEXT]

---

## Common Pitfalls

### Pitfall 1: Single-Symbol yf.download() Returns Flat Index
**What goes wrong:** `yf.download(['RELIANCE.NS'], ...)` returns a DataFrame with columns `['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']` — not MultiIndex. Calling `.xs('RELIANCE.NS', axis=1, level=1)` on a flat Index raises `TypeError`.
**Why it happens:** yfinance 0.2.40 applies MultiIndex only when multiple tickers are requested. This behavior is documented in CLAUDE.md §"1. yfinance".
**How to avoid:** Always branch on `len(symbols) == 1`. In practice AgentI4's watchlist has 0-10 symbols — the single-symbol case occurs when 9 entries have already been bought/circuit-blocked.
**Warning signs:** `TypeError: MultiIndex.xs: level 1 is not valid` or `KeyError` on `.xs()` call.
[VERIFIED: live test with yfinance 0.2.40]

### Pitfall 2: entry_price vs entry_trigger Confusion
**What goes wrong:** Using `WatchlistEntry.entry_trigger` as `entry_price` in trailing SL and partial exit calculations. `entry_trigger` is the signal threshold; actual fill price may differ.
**Why it happens:** `WatchlistEntry` (from Phase 4a) does NOT have an `entry_price` field. Developers may reach for `entry_trigger` as a proxy.
**How to avoid:** Always retrieve `entry_price` from `portfolio.get_portfolio_summary()['positions']`. The SQLite `positions` table stores `entry_price` as the actual fill (03-CONTEXT D-01).
**Warning signs:** Trailing SL activating too early/late; partial exit trigger at wrong price.
[VERIFIED: 04A-CONTEXT D-13, 03-CONTEXT D-01]

### Pitfall 3: _orb_set Timing — n=2 vs n=3 Candles
**What goes wrong:** 04B-CONTEXT D-02 mentions `n=2` but 02-CONTEXT D-06 specifies `n_minutes` parameter. With 5-minute candle data, 15 minutes = 3 candles (09:15, 09:20, 09:25). Using `n=2` gives a 10-minute ORB, missing the 09:25 candle.
**Why it happens:** D-02 says "after 2 candles: 09:15 + 09:30" — this describes wall-clock timestamps 09:15 and 09:30, but with 5m intervals there are 3 completed candles at 09:30 (not 2).
**How to avoid:** Read Phase 2's actual `Indicators.orb()` signature before implementing. If the parameter is `n_minutes`, pass `n_minutes=config.ORB_MINUTES` (15). If the parameter is `n` (candle count), pass `n=3`. See Open Questions #1.
**Warning signs:** ORB high missing the 09:25 candle's price — ORB level underestimates actual opening range.

### Pitfall 4: Cycle Crash Kills the Trading Session
**What goes wrong:** An unhandled exception in `_run_cycle()` propagates out of the `while True` loop, terminating the trading session early.
**Why it happens:** yfinance can return empty DataFrames, NaN prices, or raise network errors mid-session.
**How to avoid:** Wrap the entire cycle body in `try/except Exception as e: logger.error(...)`. The loop continues; the failed cycle is logged but execution resumes on the next tick.
**Warning signs:** Session terminates before 15:15 with a traceback; positions left open; no force square-off.
[VERIFIED: asyncio error isolation test in environment]

### Pitfall 5: Naive vs Aware Datetime Comparison
**What goes wrong:** `TypeError: can't compare offset-naive and offset-aware datetimes` if mixing `datetime.datetime.now()` (naive) with pytz-aware boundaries.
**Why it happens:** pytz-aware datetimes have tzinfo; naive datetimes do not. Python 3 refuses cross-comparison.
**How to avoid:** Always use `datetime.datetime.now(IST)` to get current time. Always use `now.replace(hour=H, minute=M, second=0, microsecond=0)` to build boundaries (preserves tzinfo).
**Warning signs:** `TypeError` at time gate check inside `_run_cycle`.
[VERIFIED: live test with Python 3.12 + pytz]

### Pitfall 6: WatchlistEntry Is Mutated (ORB Override)
**What goes wrong:** The ORB override mutates `WatchlistEntry.entry_trigger` in-place. If the same entry object is referenced by both `watchlist_map` and AgentI3's returned list (they share the same object), the override modifies the canonical watchlist.
**Why it happens:** 04B-CONTEXT D-02 says "updates each ORB_BREAKOUT WatchlistEntry's `entry_trigger = orb_high`". This is intentional — the CONTEXT explicitly describes in-place mutation.
**How to avoid:** This is the intended design. No copy needed. Both AgentI4 and any logger holding the watchlist reference see the updated value, which is correct.

---

## Code Examples

### Verified: IST Boundary Construction
```python
# Source: VERIFIED against pytz in project environment (Windows Python 3.12)
import datetime, pytz
IST = pytz.timezone("Asia/Kolkata")

def _session_boundaries():
    now = datetime.datetime.now(IST)
    return {
        "session_start":  now.replace(hour=9,  minute=15, second=0, microsecond=0),
        "entry_start":    now.replace(hour=9,  minute=30, second=0, microsecond=0),
        "entry_cutoff":   now.replace(hour=14, minute=0,  second=0, microsecond=0),
        "session_end":    now.replace(hour=15, minute=15, second=0, microsecond=0),
    }
```

### Verified: deque Circuit Detection
```python
# Source: VERIFIED against Python 3.12 stdlib in project environment
from collections import deque

price_history: dict[str, deque] = {}

def update_and_check(symbol: str, price: float) -> bool:
    if symbol not in price_history:
        price_history[symbol] = deque(maxlen=3)
    price_history[symbol].append(price)
    d = price_history[symbol]
    return len(d) == 3 and len(set(d)) == 1  # True = circuit detected
```

### Verified: yf.download() Multi-Symbol Batch with Single-Symbol Guard
```python
# Source: VERIFIED against yfinance 0.2.40 in project environment
import time
import yfinance as yf
import pandas as pd

def fetch_batch(symbols: list[str]) -> dict[str, pd.DataFrame]:
    time.sleep(0.2)
    if not symbols:
        return {}
    raw = yf.download(symbols, period="1d", interval="5m",
                      prepost=False, auto_adjust=False, progress=False)
    if raw.empty:
        return {s: pd.DataFrame() for s in symbols}

    result = {}
    if len(symbols) == 1:
        result[symbols[0]] = raw  # flat Index — no xs() needed
    else:
        for sym in symbols:
            try:
                result[sym] = raw.xs(sym, axis=1, level=1)
            except KeyError:
                result[sym] = pd.DataFrame()
    return result
```

### Verified: Partial Exit + ORB Breakeven Trailing SL
```python
# Source: D-11, D-13, D-14 from 04B-CONTEXT; math verified in environment
# Partial exit at 1:1 R:R
risk = entry_price - original_stop_loss  # e.g., 500 - 480 = 20
partial_exit_threshold = entry_price + risk  # e.g., 520
if current_price >= partial_exit_threshold and not partial_exited:
    portfolio.partial_exit(symbol, 0.5)

# GAP_AND_GO: trail SL once 1 ATR in profit
profit_threshold = entry_price + atr
if current_price >= profit_threshold:
    new_sl = current_price - (0.75 * atr)
    if new_sl > current_sl:  # SL only moves up
        portfolio.update_stop_loss(symbol, new_sl)

# ORB_BREAKOUT: move SL to breakeven after partial exit
if strategy == "ORB_BREAKOUT" and partial_exited:
    if entry_price > current_sl:
        portfolio.update_stop_loss(symbol, entry_price)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `yf.download()` returns flat columns | `yf.download()` returns MultiIndex by default for multi-ticker | yfinance 0.2.x | Must use `.xs()` or `droplevel` for multi-symbol; single-symbol still flat |
| `google-generativeai` imports | `from google import genai` (unified SDK) | Nov 2025 (frozen) | Phase 4b does not use Gemini — not relevant here |
| `ta` library for indicators | Inline pandas implementations | Phase 2 decision | No `ta` imports anywhere; ORB/ATR are pandas rolling operations |

**Deprecated/outdated:**
- `group_by='ticker'` parameter on `yf.download()`: Does NOT force MultiIndex on single-symbol inputs. Tested and confirmed — returns flat Index regardless.
- `multi_level_index=False`: Not a supported parameter in yfinance 0.2.40. Raises `TypeError: download() got an unexpected keyword argument 'multi_level_index'`. [VERIFIED]

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none — see Wave 0 |
| Quick run command | `python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGNT-09 | Loop runs 09:15-15:15, polls every 60s | unit (synthetic time injection) | `pytest tests/test_agent_i4.py::test_loop_exits_at_1515 -x` | No — Wave 0 |
| AGNT-10 | No buy before 09:30 or after 14:00 | unit (synthetic candle + time) | `pytest tests/test_agent_i4.py::test_entry_time_gates -x` | No — Wave 0 |
| AGNT-10 | Each strategy fires buy on correct candle | unit (one per strategy) | `pytest tests/test_agent_i4.py::test_gap_and_go_signal -x` | No — Wave 0 |
| AGNT-11 | force_squareoff_all() is idempotent | unit | `pytest tests/test_agent_i4.py::test_squareoff_idempotent -x` | No — Wave 0 |
| AGNT-12 | Partial exit at 1:1 R:R (GAP_AND_GO, ORB) | unit | `pytest tests/test_agent_i6.py::test_partial_exit -x` | No — Wave 0 |
| AGNT-12 | Trailing SL GAP_AND_GO (0.75 ATR) | unit | `pytest tests/test_agent_i6.py::test_trailing_sl_gap_and_go -x` | No — Wave 0 |
| AGNT-12 | ORB SL moves to breakeven after partial | unit | `pytest tests/test_agent_i6.py::test_orb_breakeven_sl -x` | No — Wave 0 |
| AGNT-12 | POSSIBLE_CIRCUIT detection (3 identical) | unit | `pytest tests/test_agent_i6.py::test_circuit_detection -x` | No — Wave 0 |

### Synthetic Candle Test Strategy

No live market data needed. All tests use synthetic DataFrames:

```python
# Pattern for synthetic candle injection (use in all test fixtures)
import pandas as pd
import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def make_candles(prices: list[float], start_hour: int = 9, start_min: int = 15):
    """Build a minimal 5-minute OHLCV DataFrame starting at given IST time."""
    base = datetime.datetime.now(IST).replace(
        hour=start_hour, minute=start_min, second=0, microsecond=0
    )
    rows = []
    for i, p in enumerate(prices):
        rows.append({
            "Open": p, "High": p + 2, "Low": p - 2,
            "Close": p, "Adj Close": p, "Volume": 500_000
        })
    index = [base + datetime.timedelta(minutes=5*i) for i in range(len(prices))]
    return pd.DataFrame(rows, index=index)

# Test GAP_AND_GO: entry_trigger = 2502 (premarket * 1.002 = 2500 * 1.002)
# Price sequence: [2490, 2498, 2503] — signal fires on candle 3
candles = make_candles([2490, 2498, 2503])
```

**Mock PaperPortfolio:** Use `unittest.mock.MagicMock()` for `portfolio` in AgentI6 tests. Assert `.sell()`, `.partial_exit()`, `.update_stop_loss()` called with correct args.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_agent_i4.py` — covers AGNT-09, AGNT-10, AGNT-11
- [ ] `tests/test_agent_i6.py` — covers AGNT-12
- [ ] `tests/conftest.py` — shared `make_candles()` fixture, mock portfolio factory
- [ ] No framework install needed — pytest 9.0.2 already available

---

## Security Domain

No new external API calls in this phase. No authentication tokens. No new environment variables. Existing `.env` security from Phase 1 is sufficient.

ASVS categories not applicable — this phase is pure internal Python logic (signal detection, position monitoring, price comparison). No user input, no web endpoints, no cryptographic operations.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | Yes | 3.12.10 | — |
| yfinance | Batch candle fetch | Yes | 0.2.40 | — |
| pandas | DataFrame operations | Yes | 2.3.3 | — |
| pytz | IST time gates | Yes (from requirements.txt) | confirmed working | — |
| pytest | Unit tests | Yes | 9.0.2 | — |
| asyncio | Polling loop | Yes (stdlib) | — | — |
| collections.deque | Circuit detection | Yes (stdlib) | — | — |

**Missing dependencies with no fallback:** None.

---

## Open Questions

1. **Indicators.orb() signature: n_minutes vs n_candles**
   - What we know: 02-CONTEXT D-06 says `n_minutes` parameter defaulting to `config.ORB_MINUTES` (15). 04B-CONTEXT D-02 says `Indicators.orb(df, n=2)` — `n` appears to mean candle count.
   - What's unclear: Was Phase 2 implemented with `n_minutes` or `n` (candle count)? With 5m candles, `n_minutes=15` → 3 candles. D-02's `n=2` gives only 10 minutes.
   - Recommendation: **Planner must read the actual `data/indicators.py` Indicators.orb() signature before writing Wave tasks.** If the parameter is `n_minutes`, use `Indicators.orb(df, n_minutes=15)`. If `n` (candle count), use `Indicators.orb(df, n=3)`. This is a one-line verification at coding time, not a blocker.

2. **PaperPortfolio.get_portfolio_summary() return shape**
   - What we know: 03-CONTEXT says it "returns capital, positions, daily P&L, win rate, trade count, halted status". The `positions` list is from the SQLite `positions` table.
   - What's unclear: Exact dict keys of each position entry — specifically whether `partial_exited` is a boolean field returned directly or requires a separate query.
   - Recommendation: **Planner must read the actual `execution/portfolio.py` implementation before writing AgentI6 tasks.** The research assumes `pos["partial_exited"]` is available in the summary — confirm this.

3. **OrderManager.calculate_quantity() caller**
   - What we know: 03-CONTEXT D-10 says `OrderManager.calculate_quantity()` is called by AgentI4 (Phase 4b). But 04A-CONTEXT canonical_refs says "D-10 — `OrderManager.calculate_quantity()` is called by AgentI4 (Phase 4b), not AgentI3".
   - What's unclear: Does AgentI4 call `order_manager.calculate_quantity()` directly, or does it call `portfolio.buy()` with a pre-computed quantity? The `buy()` method signature needs to be confirmed.
   - Recommendation: Read `execution/order_manager.py` before implementing the buy call path.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `portfolio.get_portfolio_summary()['positions']` includes `entry_price`, `partial_exited` as direct dict keys | PaperPortfolio Integration Map | AgentI6 reads wrong field or KeyError at runtime |
| A2 | `portfolio.sell(symbol, price, reason)` accepts keyword arg `reason` | Don't Hand-Roll + Code Examples | Signature mismatch; TypeError at squareoff |
| A3 | `portfolio.partial_exit(symbol, 0.5)` takes a fraction (0.5 = 50%) not a qty | Code Examples | Wrong quantity exited |
| A4 | `Indicators.orb(df, n=3)` returns `(orb_high, orb_low)` tuple for first 3 candles | ORB Override Pattern | Incorrect ORB level used as entry_trigger |

**All four assumptions are resolvable by reading the actual Phase 2 and Phase 3 implementation files before writing Wave tasks. No user confirmation required — just file reads.**

---

## Sources

### Primary (HIGH confidence)
- VERIFIED against `yfinance==0.2.40` running in project environment (2026-06-06) — MultiIndex behavior, single-symbol flat Index, xs() behavior with missing symbols
- VERIFIED against `pytz` in project environment — IST timezone-aware datetime construction and comparison
- VERIFIED against `Python 3.12.10 stdlib` — `collections.deque(maxlen=3)` circuit detection logic, `asyncio` event pattern on Windows ProactorEventLoop
- `.planning/phases/04B-market-session-agents/04B-CONTEXT.md` — all 18 locked decisions
- `.planning/phases/04A-pre-market-agents/04A-CONTEXT.md` — WatchlistEntry dataclass definition (D-13), watchlist_ready Event (D-14)
- `.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md` — PaperPortfolio methods (D-01, D-04, D-14), force_squareoff idempotency
- `.planning/phases/02-data-layer/02-CONTEXT.md` — Indicators.orb() parameter convention (D-06), yfinance fetch pattern (D-01, D-02)
- `CLAUDE.md §"1. yfinance"` — MultiIndex breaking change, prepost=False rationale, rate limiting
- `.planning/STATE.md §"Key Decisions Made"` — await asyncio.sleep(60), _squaredoff guard, prepost=False

### Secondary (MEDIUM confidence)
- `config.py` — confirmed ENTRY_START_HOUR=9, ENTRY_START_MINUTE=30, ENTRY_CUTOFF_HOUR=14, ORB_MINUTES=15, MAX_OPEN_POSITIONS=5 [VERIFIED: live file read]
- `requirements.txt` — confirmed yfinance==0.2.40, pandas>=2.0, pytz>=2024.1, pytest 9.0.2 available [VERIFIED]

### Tertiary (LOW confidence)
- None — all claims verified against running environment or authoritative planning documents.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all verified against running project environment
- yfinance batch/MultiIndex behavior: HIGH — live tests executed
- Architecture patterns: HIGH — derived from locked decisions (D-01 through D-18)
- PaperPortfolio integration: MEDIUM — method names verified in 03-CONTEXT; exact return shapes are assumed (A1-A3)
- ORB n-parameter: MEDIUM — inconsistency between 02-CONTEXT and 04B-CONTEXT flagged; see Open Question #1

**Research date:** 2026-06-06
**Valid until:** 2026-07-06 (stable libraries; yfinance behavior confirmed against pinned version)
