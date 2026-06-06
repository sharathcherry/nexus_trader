---
phase: 04B-market-session-agents
plan: 03
type: execute
wave: 2
depends_on:
  - 04B-01
  - 04B-02
files_modified:
  - agents/agent_i4.py
autonomous: true
requirements:
  - AGNT-09
  - AGNT-10

must_haves:
  truths:
    - "AgentI4.run() waits on watchlist_ready_event before starting the polling loop"
    - "The loop uses await asyncio.sleep(60) — not time.sleep — so the event loop stays free"
    - "Loop breaks when current IST time >= 15:15, then calls force_squareoff_all()"
    - "No buy is submitted before 09:30 IST or after 14:00 IST (time gate at buy submission per D-04)"
    - "GAP_AND_GO, ORB_BREAKOUT, VWAP_RECLAIM signal: current_price >= entry_trigger"
    - "GAP_FILL signal: current_price <= entry_trigger"
    - "Symbol already open in portfolio → skipped (no re-entry per D-03)"
    - "Symbol in circuit_set → skipped at entry check"
    - "After buy placed, symbol removed from watchlist_map (D-03)"
    - "AgentI6.monitor_positions() called at the START of each cycle, before entry checks (D-05)"
    - "ORB override called once per cycle via _maybe_apply_orb_override after entry checks"
    - "Entire cycle body wrapped in try/except — one bad cycle does not kill the session"
  artifacts:
    - path: "agents/agent_i4.py"
      provides: "async run() method and _run_cycle() helper"
      contains: "async def run"
    - path: "agents/agent_i4.py"
      provides: "Four strategy signal conditions"
      contains: "GAP_AND_GO"
    - path: "agents/agent_i4.py"
      provides: "Time gate at buy submission"
      contains: "entry_start"
  key_links:
    - from: "agents/agent_i4.py"
      to: "agents/agent_i6.py"
      via: "self.monitor.monitor_positions() at start of each cycle"
      pattern: "self\\.monitor\\.monitor_positions"
    - from: "agents/agent_i4.py"
      to: "execution/portfolio.py"
      via: "portfolio.buy() with qty from OrderManager.calculate_quantity()"
      pattern: "portfolio\\.buy"
---

<objective>
Wire the async polling loop and four-strategy signal evaluation into `agents/agent_i4.py`. This plan adds `async def run()`, `_run_cycle()`, and `_check_entries()` — the missing pieces that make AgentI4 a complete, runnable signal engine.

Purpose: Plans 01 and 02 built AgentI6 and AgentI4's infrastructure. This plan closes the loop: the agent now waits for the watchlist, polls every 60 seconds, evaluates signals for all four strategies, calls AgentI6 each cycle, enforces time gates at buy submission, and exits cleanly at 15:15.

Output: `agents/agent_i4.py` with complete `run()`, `_run_cycle()`, and `_check_entries()` implementations. All AGNT-09 and AGNT-10 behaviors are exercisable.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/04B-market-session-agents/04B-CONTEXT.md
@.planning/phases/04B-market-session-agents/04B-RESEARCH.md
@.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md
@.planning/phases/04A-pre-market-agents/04A-CONTEXT.md
</context>

<interfaces>
<!-- Contracts the executor builds against. -->

From agents/agent_i4.py (Plans 01+02 output):
```python
class AgentI4:
    # Already implemented (Plan 02):
    self.watchlist_map: dict[str, WatchlistEntry]
    self._squaredoff: bool
    self._orb_set: bool
    self.circuit_set: set[str]
    self.monitor: AgentI6

    def _fetch_batch(self, symbols: list[str]) -> dict[str, pd.DataFrame]: ...
    def _maybe_apply_orb_override(self, candles_map: dict, current_time) -> None: ...
    def force_squareoff_all(self, portfolio, current_prices: dict[str, float]) -> None: ...
```

From execution/order_manager.py (Phase 3 D-10, D-11):
```python
class OrderManager:
    def calculate_quantity(self, entry_price: float, stop_loss: float) -> int:
        # Uses config.RISK_PER_TRADE_PCT and config.CAPITAL to compute qty
        # Returns integer qty; returns 0 if risk parameters reject the trade
```

From execution/portfolio.py (Phase 3 D-13):
```python
def buy(self, symbol: str, price: float, qty: int,
        stop_loss: float, target: float, strategy: str) -> bool:
    # Returns True on success, False on rejection (halted, max_positions, etc.)
```

From config.py (per 04B-CONTEXT code_context):
```python
config.ENTRY_START      # hour=9, minute=30 (or separate ENTRY_START_HOUR/MINUTE)
config.NO_ENTRY_AFTER   # hour=14, minute=0
config.FORCE_SQUAREOFF_TIME  # hour=15, minute=15
```

AgentI4.run() signature (D-16):
```python
async def run(
    self,
    watchlist: list,                    # List[WatchlistEntry] — already loaded into self.watchlist_map by __init__
    portfolio,                          # PaperPortfolio instance
    watchlist_ready_event,              # asyncio.Event — wait before starting
    order_manager = None,               # OrderManager (optional; if None, qty=1 fallback)
) -> None:
```
</interfaces>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement async run() loop with time gate and cycle dispatch</name>
  <files>agents/agent_i4.py</files>
  <read_first>
    - agents/agent_i4.py — existing __init__, _fetch_batch, _maybe_apply_orb_override, force_squareoff_all from Plan 02
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-16 (run() structure: wait → sleep → check time → cycle), D-04 (time gate at buy submission), D-05 (AgentI6 called first)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — Pattern 1 (asyncio loop with IST time gate), Pattern 4 (IST time comparisons), Pattern 7 (per-cycle error isolation), Anti-Patterns (time.sleep vs await asyncio.sleep, naive vs aware datetimes)
    - .planning/STATE.md — §"Key Decisions Made" — `await asyncio.sleep(60)` not `time.sleep(60)`
    - config.py — read actual config attribute names for time boundaries (ENTRY_START_HOUR / NO_ENTRY_AFTER_HOUR or similar)
  </read_first>
  <behavior>
    - Test: run() awaits watchlist_ready_event.wait() before entering the loop (inject a pre-set event to allow immediate start)
    - Test: loop exits when current IST time >= 15:15 (inject mocked time returning 15:15)
    - Test: force_squareoff_all is called after loop exit
    - Test: cycle body wrapped in try/except — an exception in _run_cycle does not propagate out of run()
    - Test: await asyncio.sleep(60) is called once per iteration (verify asyncio.sleep is used, not time.sleep)
  </behavior>
  <action>
    Add `async def run(self, watchlist, portfolio, watchlist_ready_event, order_manager=None) -> None` to `AgentI4`.

    Body:
    1. `await watchlist_ready_event.wait()` — blocks until pre-market pipeline sets event (D-16).
    2. `logger.info("AgentI4: watchlist ready — starting market session loop")`.
    3. `while True:`.
    4.   `await asyncio.sleep(60)` — MUST be `await asyncio.sleep`, never `time.sleep` (STATE.md pitfall).
    5.   `current_time = datetime.datetime.now(IST)`.
    6.   `session_end = current_time.replace(hour=15, minute=15, second=0, microsecond=0)`.
    7.   `if current_time >= session_end: break`.
    8.   `try: await self._run_cycle(portfolio, current_time, order_manager)`.
    9.   `except Exception as e: logger.error(f"Cycle error (continuing): {e}", exc_info=True)`.
    10. After loop: `last_prices = {sym: 0.0 for sym in self.watchlist_map}` (best-effort empty prices; force_squareoff uses entry_price fallback per Plan 02).
    11. `self.force_squareoff_all(portfolio, last_prices)`.

    Also add `async def _run_cycle(self, portfolio, current_time, order_manager) -> None` stub that calls:
    - `candles_map = self._fetch_batch(list(self.watchlist_map.keys()))`.
    - `self.monitor.monitor_positions(portfolio, self.watchlist_map, candles_map, current_time, self.circuit_set)`.
    - `self._check_entries(candles_map, portfolio, current_time, order_manager)`.
    - `self._maybe_apply_orb_override(candles_map, current_time)`.

    `_check_entries` is implemented in Task 2 below. For now `_run_cycle` may call it — Task 2 adds the actual method body.
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i4.py::test_loop_exits_at_1515 -x -q</automated>
  </verify>
  <done>
    run() awaits watchlist_ready_event, loops with await asyncio.sleep(60), breaks at 15:15, calls force_squareoff_all after exit, and wraps cycle body in try/except. Test test_loop_exits_at_1515 passes.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement four-strategy signal evaluation and buy submission with time gates</name>
  <files>agents/agent_i4.py</files>
  <read_first>
    - agents/agent_i4.py — existing class (Tasks 1 above + Plan 02 output)
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-01 (four signal conditions), D-03 (one buy per symbol, remove from candidates), D-04 (time gate at buy submission), D-09 (circuit_set skip)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — "AgentI4 buy() call sequence" in PaperPortfolio Integration Map, Pitfall 2 (entry_trigger vs entry_price), Pattern 4 (IST time comparisons)
    - .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md — D-13 (buy() returns bool, never raises)
    - execution/order_manager.py — read actual calculate_quantity() signature
  </read_first>
  <behavior>
    - Test (time gate): _check_entries called with current_time=09:15 → portfolio.buy never called (before entry_start)
    - Test (time gate): _check_entries called with current_time=14:30 → portfolio.buy never called (after entry_cutoff)
    - Test (time gate): _check_entries called with current_time=10:00 → buy eligible if signal conditions met
    - Test (GAP_AND_GO signal): current_price >= entry_trigger → portfolio.buy called with correct args; symbol removed from watchlist_map
    - Test (GAP_FILL signal): current_price <= entry_trigger → portfolio.buy called
    - Test (ORB_BREAKOUT signal): current_price >= entry_trigger → portfolio.buy called
    - Test (VWAP_RECLAIM signal): current_price >= entry_trigger → portfolio.buy called
    - Test (no signal): price does not meet condition → portfolio.buy NOT called
    - Test (already open): symbol in portfolio.get_portfolio_summary()["positions"] → buy skipped
    - Test (circuit_set): symbol in self.circuit_set → buy skipped
    - Test (buy success=False): portfolio.buy returns False → symbol NOT removed from watchlist_map (can retry next cycle)
  </behavior>
  <action>
    Add `_check_entries(self, candles_map: dict, portfolio, current_time, order_manager) -> None` to `AgentI4`.

    Build time gate:
    - `entry_start = current_time.replace(hour=9, minute=30, second=0, microsecond=0)`.
    - `entry_cutoff = current_time.replace(hour=14, minute=0, second=0, microsecond=0)`.
    - `can_buy = entry_start <= current_time <= entry_cutoff` (per D-04).

    Get currently open symbols for re-entry check:
    - `open_symbols = {p["symbol"] for p in portfolio.get_portfolio_summary().get("positions", [])}`.

    For each `sym` in `list(self.watchlist_map.keys())` (copy keys to allow deletion during iteration):
    - Skip if `sym in self.circuit_set` (D-09).
    - Skip if `sym in open_symbols` (D-03, already open).
    - `entry = self.watchlist_map[sym]`.
    - Get current price: `df = candles_map.get(sym, pd.DataFrame())`. If `df.empty`: continue. `current_price = float(df["Close"].iloc[-1])`.
    - Evaluate signal (D-01):
      - `GAP_AND_GO`: `signal = current_price >= entry.entry_trigger`
      - `ORB_BREAKOUT`: `signal = current_price >= entry.entry_trigger`
      - `VWAP_RECLAIM`: `signal = current_price >= entry.entry_trigger`
      - `GAP_FILL`: `signal = current_price <= entry.entry_trigger`
    - If `not signal`: continue.
    - If `not can_buy`: log DEBUG `f"Signal for {sym} outside entry window — skip buy"`; continue (signal noted but not acted on per D-04).
    - Compute qty:
      - If `order_manager is not None`: `qty = order_manager.calculate_quantity(current_price, entry.stop_loss)`.
      - Else: `qty = 1` (test/fallback mode).
    - If `qty <= 0`: continue.
    - `success = portfolio.buy(sym, current_price, qty, entry.stop_loss, entry.target, entry.strategy)`.
    - If `success`: `del self.watchlist_map[sym]`; log INFO `f"BUY {sym} at {current_price:.2f} qty={qty} strategy={entry.strategy}"`.
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i4.py::test_entry_time_gates tests/test_agent_i4.py::test_gap_and_go_signal tests/test_agent_i4.py::test_gap_fill_signal tests/test_agent_i4.py::test_orb_breakout_signal tests/test_agent_i4.py::test_vwap_reclaim_signal -x -q</automated>
  </verify>
  <done>
    _check_entries enforces time gates: no buy before 09:30 or after 14:00. All four strategy signal conditions (three >= and one <=) trigger portfolio.buy correctly. Symbol removed from watchlist_map on successful buy. Circuit and open-position skips work. Tests pass.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| yfinance candle data → signal evaluation | Close price used for trigger comparison; NaN or zero price must be handled |
| asyncio event loop → polling loop | time.sleep() would block the loop; only await asyncio.sleep() permitted |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04B-08 | Denial of Service | time.sleep(60) in async context | mitigate | Must use await asyncio.sleep(60); verified in STATE.md critical pitfall #5 |
| T-04B-09 | Denial of Service | Unhandled exception in _run_cycle kills session | mitigate | Outer try/except in run() loop: log error and continue; session survives bad cycles |
| T-04B-10 | Tampering | Naive vs aware datetime comparison in time gate | mitigate | Always build boundaries via current_time.replace() (preserves tzinfo); never mix naive datetimes |
| T-04B-11 | Elevation of Privilege | Re-entry after partial exit (buy same symbol again) | mitigate | open_symbols set checked each cycle prevents re-entry per D-03 |
| T-04B-12 | Tampering | Buy submitted with qty=0 | mitigate | qty <= 0 guard: skip buy if calculate_quantity returns 0 |
| T-04B-SC | Tampering | npm/pip/cargo installs | accept | No new package installs in this plan |
</threat_model>

<verification>
## Plan-Level Checks

```bash
# Import and instantiation
python -c "
from agents.agent_i4 import AgentI4
import inspect, asyncio
assert inspect.iscoroutinefunction(AgentI4.run), 'run() must be async'
print('async run — OK')
"

# await asyncio.sleep present (not time.sleep)
python -c "
src = open('agents/agent_i4.py').read()
assert 'await asyncio.sleep(60)' in src, 'missing await asyncio.sleep'
assert 'time.sleep(60)' not in src, 'blocking time.sleep found'
print('asyncio.sleep check — OK')
"

# All four strategies in signal evaluation
python -c "
src = open('agents/agent_i4.py').read()
for s in ('GAP_AND_GO', 'GAP_FILL', 'ORB_BREAKOUT', 'VWAP_RECLAIM'):
    assert s in src, f'missing strategy: {s}'
print('four strategies — OK')
"

# Signal loop tests
python -m pytest tests/test_agent_i4.py -x -q
```
</verification>

<success_criteria>
- `async def run()` in agents/agent_i4.py awaits watchlist_ready_event and uses `await asyncio.sleep(60)`
- Loop exits when IST time >= 15:15 and calls force_squareoff_all
- All four strategy signal conditions coded: GAP_AND_GO/ORB_BREAKOUT/VWAP_RECLAIM use `>=`, GAP_FILL uses `<=`
- Time gate enforced at buy submission: no buy before 09:30 or after 14:00 IST
- Symbol removed from watchlist_map on successful buy (no re-entry)
- circuit_set and open_symbols checks both skip the symbol before signal evaluation
- `python -m pytest tests/test_agent_i4.py -x -q` exits 0 with all signal and loop tests green
</success_criteria>

<output>
Create `.planning/phases/04B-market-session-agents/04B-03-SUMMARY.md` when done
</output>
