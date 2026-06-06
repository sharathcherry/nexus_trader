# Phase 4b: Market Session Agents - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

AgentI4 (signal engine) and AgentI6 (position monitor) that drive the market session from 09:15 to 15:15 IST. AgentI4 polls every 60 seconds, checks entry conditions for each watchlist stock, and submits buys via PaperPortfolio. AgentI6 monitors open positions each cycle for exits, trailing SL updates, and circuit detection. No APScheduler, no orchestrator wiring — that is Phase 5. Delivers `agents/agent_i4.py` and `agents/agent_i6.py`.

</domain>

<decisions>
## Implementation Decisions

### Strategy signal conditions
- **D-01:** Pure price trigger — no additional indicator confirmations. Signal condition per strategy:
  - `GAP_AND_GO`: `current_price >= entry_trigger` (breakout above 0.2% over premarket)
  - `ORB_BREAKOUT`: `current_price >= entry_trigger` (breakout above actual ORB high, set at 09:30)
  - `VWAP_RECLAIM`: `current_price >= entry_trigger` (price above VWAP proxy trigger)
  - `GAP_FILL`: `current_price <= entry_trigger` (pullback to 0.2% below premarket)
- **D-02:** ORB_BREAKOUT entry_trigger override: at 09:30 (after 2 candles: 09:15 + 09:30), AgentI4 calls `Indicators.orb(df, n=2)` and updates each ORB_BREAKOUT WatchlistEntry's `entry_trigger = orb_high`. Placeholder from Phase 4a (premarket * 1.005) is replaced in-place.
- **D-03:** Each signal fires at most once per symbol per session. After a buy is placed for a symbol → remove from active watchlist candidates (no re-entry). Already-open position for same symbol → skip.
- **D-04:** Time gates enforced at buy submission, not at signal evaluation. AgentI4 evaluates signals all cycles; `portfolio.buy()` call is wrapped: `if current_time < 09:30 or current_time > 14:00: skip_buy()`. Signal evaluation still runs (so ORB override at 09:30 works correctly before 09:30).

### AgentI6 structure
- **D-05:** Separate class in `agents/agent_i6.py`. Single public method: `monitor_positions(portfolio, watchlist_map, current_prices, current_time)`. Returns list of actions taken (for logging). AgentI4 calls it at the start of each polling cycle, before checking entries.
- **D-06:** `watchlist_map` is a `dict[str, WatchlistEntry]` (symbol → entry), passed from AgentI4. AgentI6 uses it to read `stop_loss`, `target`, `strategy`, `atr` for each open position.
- **D-07:** Phase 5 orchestrator imports AgentI4 only. AgentI6 is an internal dependency — AgentI4 instantiates it in `__init__` as `self.monitor = AgentI6()`.

### POSSIBLE_CIRCUIT behavior
- **D-08:** AgentI6 tracks last 3 prices per open position in a `dict[str, deque]` (maxlen=3). If all 3 values identical → `POSSIBLE_CIRCUIT` detected.
- **D-09:** On detection: log `WARNING: POSSIBLE_CIRCUIT detected for {symbol} — skipping for remainder of session`. Add symbol to `self.circuit_set` (session-level set). All subsequent cycles skip entry checks AND exit checks for that symbol. `circuit_set` resets on new session (AgentI4 re-instantiation).
- **D-10:** `circuit_set` lives in AgentI4 (entry gate) AND AgentI6 (exit skip). AgentI4 passes `circuit_set` reference to AgentI6 on each call so both use the same set object.

### Partial exit scope
- **D-11:** Partial exit at 1:1 R:R applies to `GAP_AND_GO` and `ORB_BREAKOUT` only. Rule: when `current_price >= entry_price + (entry_price - stop_loss)` → `portfolio.partial_exit(symbol, 0.5)` (exit 50%). Trailing SL activates immediately after partial exit.
- **D-12:** `GAP_FILL` and `VWAP_RECLAIM` hold for full target — no partial exit. Exit only on: target hit, SL hit, or 15:15 force square-off.
- **D-13:** Trailing SL for `GAP_AND_GO` (from PORT-13): trail at `current_price - 0.75 * atr` once `current_price >= entry_price + atr` (1 ATR in profit). SL only moves up, never down.
- **D-14:** Trailing SL for `ORB_BREAKOUT` (from PORT-13): move SL to breakeven (`entry_price`) when 1:1 R:R hit. No further trailing — hold to target.
- **D-15:** `GAP_FILL` and `VWAP_RECLAIM` have fixed SL throughout session (no trailing).

### AgentI4 loop structure
- **D-16:** `async def run(watchlist, portfolio, watchlist_ready_event)` — waits for `watchlist_ready.wait()` before starting. Then: `while True: await asyncio.sleep(60); if current_time > 15:15: break; cycle()`. Loop runs until 15:15, then calls `force_squareoff_all()`.
- **D-17:** `force_squareoff_all()` is idempotent via `self._squaredoff = False` guard (locked from STATE.md). APScheduler `date` job in Phase 5 also calls it as backup.
- **D-18:** Each cycle: fetch intraday candles for ALL watchlist symbols in one batch yfinance download, then extract per-symbol data. Avoids N individual API calls per cycle. 0.2s sleep before any batch fetch.

### Claude's Discretion
- Exact log messages for each trade action (buy, partial exit, SL hit, target hit)
- Whether AgentI4 also prints a live positions table each cycle (tabulate)
- Deque import (`from collections import deque`) and price tracking data structure internals

</decisions>

<specifics>
## Specific Ideas

- **ORB override timing**: The 09:30 ORB override happens on the 3rd polling cycle (09:15 start, 09:16 poll 1, 09:17 poll 2... actually at 09:30 the first 15-min candle closes). AgentI4 should check `if current_time >= 09:30 and not self._orb_set` → fetch candles, compute ORB, update entry_triggers, set `self._orb_set = True`. One-time operation per session.
- **Phase 4a WatchlistEntry passthrough**: AgentI4 receives the list from AgentI3 (via Phase 5 orchestrator). AgentI4 converts to `dict[str, WatchlistEntry]` keyed by symbol for O(1) lookup per cycle.
- **yfinance batch fetch**: `yf.download(symbols_list, period="1d", interval="5m", prepost=False, auto_adjust=False)` returns MultiIndex columns. Use `.xs(symbol, axis=1, level=1)` to extract per-symbol OHLCV.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Agent requirements
- `.planning/REQUIREMENTS.md` §"Agents" (AGNT-09 through AGNT-12) — complete requirement set for this phase

### Prior phase decisions (MUST read)
- `.planning/phases/04A-pre-market-agents/04A-CONTEXT.md` — WatchlistEntry dataclass (D-13), ORB placeholder entry_trigger (D-11 + specifics), watchlist_ready Event pattern (D-14), strategy assignment rules (D-09)
- `.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md` — PaperPortfolio.partial_exit(), update_trailing_stops() PORT-13 spec, force_squareoff_all() idempotency pattern
- `.planning/STATE.md` §"Key Decisions Made" — `await asyncio.sleep(60)`, force square-off dual safety, `_squaredoff` guard, `prepost=False` on yfinance

### Data layer patterns
- `.planning/phases/02-data-layer/02-CONTEXT.md` — `Indicators.orb()`, `Indicators.vwap()`, yfinance batch download pattern

### Project constraints
- `.planning/ROADMAP.md` §"Phase 4b: Market Session Agents" — success criteria (4 items defining done)
- `CLAUDE.md` §"1. yfinance" — rate limiting behavior, 0.2s delay, MultiIndex column handling, `prepost=False` rationale

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (exist after Phases 1–4a)
- `agents/agent_i3.py` → `WatchlistEntry` dataclass — imported by AgentI4
- `execution/portfolio.py` → `PaperPortfolio` — `buy()`, `partial_exit()`, `update_stop_loss()`, `get_portfolio_summary()`
- `execution/order_manager.py` → `OrderManager.calculate_quantity()`, `check_and_execute_exits()`
- `data/market_data.py` → `MarketDataFetcher.get_intraday_candles()`
- `data/indicators.py` → `Indicators.orb()`, `Indicators.vwap()`, `Indicators.volume_ratio()`
- `config.py` → `config.MAX_OPEN_POSITIONS` (5), `config.NO_ENTRY_AFTER` (14:00), `config.ENTRY_START` (09:30), `config.FORCE_SQUAREOFF_TIME` (15:15)

### Established Patterns
- Async `run()` with `await asyncio.sleep(60)` — same pattern as other agents
- `watchlist_ready.wait()` before starting loop — from Phase 4a D-14
- `prepost=False`, `auto_adjust=False` on all yfinance calls
- 0.2s delay before bulk API calls — from DATA-09

### Integration Points
- AgentI4 receives `List[WatchlistEntry]` from Phase 5 orchestrator (AgentI3 output)
- AgentI4 holds reference to `PaperPortfolio` instance (shared with orchestrator)
- AgentI4 signals loop end to Phase 5 orchestrator (returns after force square-off)
- AgentI4c (Phase 4c) reads portfolio daily report AFTER AgentI4 exits loop

</code_context>

<deferred>
## Deferred Ideas

- RSI/volume confirmation overlays for signal quality — deferred (pure price trigger chosen)
- Re-entry logic after partial exit — out of scope v1
- Live positions table printed each cycle — Claude's discretion

</deferred>

---

*Phase: 04B-market-session-agents*
*Context gathered: 2026-06-06*
