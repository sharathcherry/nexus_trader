---
phase: 04B-market-session-agents
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - agents/agent_i4.py
autonomous: true
requirements:
  - AGNT-09
  - AGNT-10
  - AGNT-11

must_haves:
  truths:
    - "AgentI4 class exists with __init__ that instantiates AgentI6 as self.monitor and initializes all session-state flags"
    - "AgentI4 converts input List[WatchlistEntry] to dict[str, WatchlistEntry] keyed by symbol for O(1) lookup"
    - "_fetch_batch handles the single-symbol flat-Index case (len(symbols)==1) and the multi-symbol MultiIndex case via .xs()"
    - "Empty DataFrame check (df.empty) is used after batch fetch — no try/except KeyError"
    - "ORB override fires exactly once per session when current_time >= 09:30 via _orb_set flag"
    - "0.2s time.sleep() precedes every batch yfinance download"
    - "_squaredoff flag makes force_squareoff_all() idempotent"
  artifacts:
    - path: "agents/agent_i4.py"
      provides: "AgentI4 class skeleton with __init__, _fetch_batch, _maybe_apply_orb_override, force_squareoff_all"
      exports: ["AgentI4"]
      contains: "class AgentI4"
    - path: "agents/agent_i4.py"
      provides: "yfinance batch fetch with single-symbol branch"
      contains: "len(symbols) == 1"
    - path: "agents/agent_i4.py"
      provides: "ORB override with _orb_set guard"
      contains: "_orb_set"
  key_links:
    - from: "agents/agent_i4.py"
      to: "agents/agent_i6.py"
      via: "self.monitor = AgentI6() in __init__"
      pattern: "self\\.monitor\\s*=\\s*AgentI6"
    - from: "agents/agent_i4.py"
      to: "data/indicators.py"
      via: "Indicators.orb(df, n_minutes=...) in _maybe_apply_orb_override"
      pattern: "Indicators\\.orb"
---

<objective>
Build the AgentI4 class skeleton and infrastructure in `agents/agent_i4.py` — class definition, `__init__`, yfinance batch fetch helper, ORB override logic, and `force_squareoff_all()`. The signal evaluation loop and watchlist_ready wait are covered in Plan 03 (Wave 2).

Purpose: Establishing the class contract, data fetch layer, and one-time ORB override before the full async loop is wired. Plan 03 depends on these foundations being correct.

Output: `agents/agent_i4.py` with `class AgentI4`, `__init__`, `_fetch_batch`, `_maybe_apply_orb_override`, and `force_squareoff_all` — all individually testable without running the async loop.
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
@.planning/phases/04A-pre-market-agents/04A-CONTEXT.md
@.planning/phases/02-data-layer/02-CONTEXT.md
</context>

<interfaces>
<!-- Contracts the executor needs. Extracted from planning context. -->

From agents/models.py (WatchlistEntry — Phase 4a D-13):
```python
@dataclass
class WatchlistEntry:
    symbol: str
    strategy: str   # "GAP_AND_GO" | "ORB_BREAKOUT" | "GAP_FILL" | "VWAP_RECLAIM"
    entry_trigger: float   # mutable — ORB override replaces in-place
    stop_loss: float
    target: float
    atr: float
    # ... other fields
```

From data/indicators.py (Phase 2 D-06):
```python
# Indicators.orb() signature — MUST read actual file before implementing the call.
# 02-CONTEXT D-06: parameter is n_minutes defaulting to config.ORB_MINUTES (15).
# Returns (orb_high, orb_low) tuple.
# With 5-minute candles: n_minutes=15 → 3 candles (09:15, 09:20, 09:25).
# If parameter is `n` (candle count, not minutes), use n=3 instead.
# Verify by reading data/indicators.py before coding the orb call.
@staticmethod
def orb(df: pd.DataFrame, n_minutes: int = 15) -> tuple[float, float]: ...
# OR possibly:
@staticmethod
def orb(df: pd.DataFrame, n: int = 3) -> tuple[float, float]: ...
```

From execution/portfolio.py (Phase 3 D-01):
```python
def get_portfolio_summary(self) -> dict:
    # {"positions": [{"symbol": str, "entry_price": float, ...}], ...}
def sell(self, symbol: str, price: float, reason: str = "") -> bool: ...
```

AgentI4 public interface (per D-16, D-17):
```python
class AgentI4:
    def __init__(self, watchlist: list) -> None:
        # watchlist: List[WatchlistEntry] from AgentI3
        # Builds self.watchlist_map: dict[str, WatchlistEntry]
        # Sets self._squaredoff = False
        # Sets self._orb_set = False
        # Sets self.circuit_set: set[str] = set()
        # Instantiates self.monitor = AgentI6()

    def _fetch_batch(self, symbols: list[str]) -> dict[str, pd.DataFrame]: ...
    def _maybe_apply_orb_override(self, candles_map: dict, current_time) -> None: ...
    def force_squareoff_all(self, portfolio, current_prices: dict[str, float]) -> None: ...
    async def run(self, watchlist, portfolio, watchlist_ready_event) -> None: ...
        # async run() implemented in Plan 03
```
</interfaces>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: AgentI4 __init__ and yfinance batch fetch infrastructure</name>
  <files>agents/agent_i4.py</files>
  <read_first>
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-03 (watchlist_map keyed by symbol), D-07 (AgentI6 as self.monitor), D-10 (circuit_set shared reference), D-17 (_squaredoff guard), D-18 (batch fetch with 0.2s sleep)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — Pattern 2 (yfinance batch download, len==1 branch, .xs() pattern), Pitfall 1 (single-symbol flat Index TypeError)
    - CLAUDE.md — §"1. yfinance" — MultiIndex column handling, prepost=False, auto_adjust=False rationale
    - .planning/phases/04A-pre-market-agents/04A-CONTEXT.md — D-13 (WatchlistEntry dataclass)
  </read_first>
  <behavior>
    - Test: AgentI4.__init__([entry1, entry2]) produces self.watchlist_map == {"SYM1": entry1, "SYM2": entry2}
    - Test: self._squaredoff is False after __init__
    - Test: self._orb_set is False after __init__
    - Test: self.circuit_set is an empty set after __init__
    - Test: self.monitor is an AgentI6 instance after __init__
    - Test: _fetch_batch([]) returns {}
    - Test: _fetch_batch with single symbol — returns dict keyed by that symbol with a non-MultiIndex DataFrame (mock yf.download to return flat Index df)
    - Test: _fetch_batch with two symbols — uses .xs() to extract per-symbol (mock yf.download to return MultiIndex df)
    - Test: _fetch_batch with yf.download returning empty DataFrame — returns {sym: pd.DataFrame()} for all symbols
  </behavior>
  <action>
    Create `agents/agent_i4.py`. At module level: `import asyncio, time, datetime, pytz, yfinance as yf, pandas as pd`. Import `from collections import deque`. Import `from agents.agent_i6 import AgentI6`, `from agents.models import WatchlistEntry` (or `from agents.agent_i3 import WatchlistEntry` — use whichever file Phase 4a placed WatchlistEntry). Import `from data.indicators import Indicators`. Import `from config import config`, `from utils.logger import setup_logger`. Module-level `logger = setup_logger(__name__)` and `IST = pytz.timezone("Asia/Kolkata")`.

    Implement `AgentI4.__init__(self, watchlist: list)`:
    - `self.watchlist_map: dict[str, WatchlistEntry] = {e.symbol: e for e in watchlist}`.
    - `self._squaredoff: bool = False`.
    - `self._orb_set: bool = False`.
    - `self.circuit_set: set[str] = set()`.
    - `self.monitor = AgentI6()`.

    Implement `_fetch_batch(self, symbols: list[str]) -> dict[str, pd.DataFrame]`:
    - If `not symbols`: return `{}`.
    - `time.sleep(0.2)` — rate-limit guard (DATA-09, STATE.md pitfall).
    - Call `yf.download(symbols, period="1d", interval="5m", prepost=False, auto_adjust=False, progress=False)`.
    - If `raw.empty`: return `{s: pd.DataFrame() for s in symbols}`.
    - Branch: `if len(symbols) == 1: result = {symbols[0]: raw}`.
    - Else: for each sym call `raw.xs(sym, axis=1, level=1)`; on `KeyError` store `pd.DataFrame()`.
    - Return result dict.

    Do NOT implement `run()` or `_check_entries()` yet — those are Plan 03.
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i4.py::test_init tests/test_agent_i4.py::test_fetch_batch -x -q</automated>
  </verify>
  <done>
    agents/agent_i4.py exists with class AgentI4. __init__ produces correct watchlist_map, _squaredoff=False, _orb_set=False, empty circuit_set, AgentI6 instance. _fetch_batch handles empty list, single-symbol (no .xs()), multi-symbol (.xs()), and empty-DataFrame cases. Tests pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: ORB override and force_squareoff_all</name>
  <files>agents/agent_i4.py</files>
  <read_first>
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-02 (ORB override at 09:30, updates entry_trigger in-place), D-17 (_squaredoff idempotency), D-16 (force_squareoff called after loop exits)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — Pattern 5 (force_squareoff_all idempotency), Pattern 6 (ORB override with _orb_set guard), Pitfall 3 (n=2 vs n=3 — read actual Indicators.orb() signature)
    - data/indicators.py — read the actual Indicators.orb() method signature to determine if the parameter is n_minutes or n (candle count)
    - .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md — D-14 (_squaredoff dual safety; AgentI4 flag is separate from PaperPortfolio's force_squaredoff)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — Pattern 4 (IST time comparison)
  </read_first>
  <behavior>
    - Test: _maybe_apply_orb_override when _orb_set=True → nothing happens (entry_trigger unchanged)
    - Test: _maybe_apply_orb_override when current_time < 09:30 → nothing happens
    - Test: _maybe_apply_orb_override when current_time >= 09:30 and _orb_set=False: sets _orb_set=True, updates entry_trigger for ORB_BREAKOUT symbols to orb_high returned by Indicators.orb()
    - Test: _maybe_apply_orb_override with a non-ORB_BREAKOUT symbol (e.g., GAP_AND_GO) → entry_trigger unchanged
    - Test: _maybe_apply_orb_override with empty candle DataFrame for an ORB_BREAKOUT symbol → entry_trigger unchanged (not enough candles)
    - Test: force_squareoff_all when _squaredoff=False → calls portfolio.sell() for each open position, sets _squaredoff=True
    - Test: force_squareoff_all called twice — second call is a no-op (portfolio.sell not called again)
    - Test: force_squareoff_all with no open positions → no sell calls, _squaredoff=True
  </behavior>
  <action>
    Add two methods to `AgentI4` in `agents/agent_i4.py`.

    `_maybe_apply_orb_override(self, candles_map: dict, current_time: datetime.datetime) -> None`:
    - Build `orb_threshold = current_time.replace(hour=9, minute=30, second=0, microsecond=0)`.
    - Early return if `self._orb_set or current_time < orb_threshold`.
    - Set `self._orb_set = True`.
    - For each `sym, entry` in `self.watchlist_map.items()` where `entry.strategy == "ORB_BREAKOUT"`:
      - `df = candles_map.get(sym, pd.DataFrame())`. If `df.empty or len(df) < 3`: continue (keep placeholder per research pitfall 3).
      - Call `Indicators.orb(df, ...)` — use the signature found by reading `data/indicators.py`. If the parameter is `n_minutes`, pass `n_minutes=config.ORB_MINUTES` (15). If the parameter is `n` (candle count), pass `n=3`. Store return as `(orb_high, orb_low)`.
      - If `orb_high and orb_high > 0`: `entry.entry_trigger = orb_high`; log INFO `f"ORB override {sym}: entry_trigger → {orb_high:.2f}"`.

    `force_squareoff_all(self, portfolio, current_prices: dict[str, float]) -> None`:
    - If `self._squaredoff`: log INFO "force_squareoff_all: already executed — skipping"; return.
    - Set `self._squaredoff = True`.
    - `summary = portfolio.get_portfolio_summary()`.
    - For each `pos` in `summary.get("positions", [])`:
      - `sym = pos["symbol"]`; `price = current_prices.get(sym, pos["entry_price"])` (fallback to entry_price if no current price).
      - `portfolio.sell(sym, price, reason="FORCE_SQUAREOFF")`.
    - Log INFO "force_squareoff_all: all positions closed".
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i4.py::test_orb_override tests/test_agent_i4.py::test_squareoff_idempotent -x -q</automated>
  </verify>
  <done>
    _maybe_apply_orb_override sets entry_trigger for ORB_BREAKOUT symbols exactly once at 09:30, leaves other strategies untouched, and handles empty DataFrames safely. force_squareoff_all closes all positions on first call and is a no-op on subsequent calls. Tests pass.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| yfinance → _fetch_batch | Remote HTTP call; may return empty DataFrame, partial data, or raise on 429 |
| WatchlistEntry.entry_trigger mutation | ORB override mutates the entry object in-place; intentional per D-02 |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04B-04 | Denial of Service | _fetch_batch — yfinance 429 returns empty DataFrame | mitigate | Check raw.empty before processing; empty → return dict of empty DataFrames; polling continues next cycle |
| T-04B-05 | Tampering | yf.download single-symbol flat Index vs MultiIndex | mitigate | Mandatory len(symbols)==1 branch guards against TypeError on .xs() |
| T-04B-06 | Denial of Service | force_squareoff_all called from both loop and APScheduler | mitigate | _squaredoff guard makes method idempotent; second call is a no-op |
| T-04B-07 | Spoofing | ORB high calculated from incomplete candles (< 3 rows) | mitigate | len(df) < 3 check keeps placeholder entry_trigger; retry implicit on next cycle |
| T-04B-SC | Tampering | npm/pip/cargo installs | accept | No new package installs in this plan |
</threat_model>

<verification>
## Plan-Level Checks

```bash
# Import works
python -c "from agents.agent_i4 import AgentI4; print('import OK')"

# Single-symbol branch present
python -c "src=open('agents/agent_i4.py').read(); assert 'len(symbols) == 1' in src; print('single-symbol guard — OK')"

# _squaredoff guard present
python -c "src=open('agents/agent_i4.py').read(); assert '_squaredoff' in src; print('squaredoff guard — OK')"

# Tests pass
python -m pytest tests/test_agent_i4.py::test_init tests/test_agent_i4.py::test_fetch_batch tests/test_agent_i4.py::test_orb_override tests/test_agent_i4.py::test_squareoff_idempotent -x -q
```
</verification>

<success_criteria>
- `agents/agent_i4.py` exists with `class AgentI4`
- `__init__` builds `watchlist_map` as `dict[str, WatchlistEntry]` keyed by symbol
- `_fetch_batch` branches on `len(symbols) == 1` before calling `.xs()`
- `_maybe_apply_orb_override` sets `_orb_set = True` on first run at/after 09:30 and updates ORB_BREAKOUT entry_triggers
- `force_squareoff_all` is idempotent via `_squaredoff` flag — second call is a no-op
- `python -m pytest tests/test_agent_i4.py -x -q` passes all init/fetch/orb/squareoff tests (signal loop tests added in Plan 03)
</success_criteria>

<output>
Create `.planning/phases/04B-market-session-agents/04B-02-SUMMARY.md` when done
</output>
