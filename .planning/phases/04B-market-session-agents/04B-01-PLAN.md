---
phase: 04B-market-session-agents
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - agents/agent_i6.py
autonomous: true
requirements:
  - AGNT-12

must_haves:
  truths:
    - "AgentI6.monitor_positions() checks each open position for circuit, hard exits, partial exit at 1:1 R:R, and trailing SL updates"
    - "POSSIBLE_CIRCUIT is flagged when the same price appears in 3 consecutive polls for a symbol"
    - "Partial exit fires only for GAP_AND_GO and ORB_BREAKOUT at 1:1 R:R; GAP_FILL and VWAP_RECLAIM hold for full target"
    - "Trailing SL for GAP_AND_GO trails at current_price - 0.75 * atr once 1 ATR in profit, never moves down"
    - "Trailing SL for ORB_BREAKOUT moves to entry_price (breakeven) after partial exit, no further trailing"
    - "GAP_FILL and VWAP_RECLAIM have fixed SL throughout the session"
    - "AgentI6 never computes brokerage or stores financial state — all mutations delegated to PaperPortfolio"
  artifacts:
    - path: "agents/agent_i6.py"
      provides: "AgentI6 class — stateful position monitor"
      exports: ["AgentI6"]
      contains: "class AgentI6"
    - path: "agents/agent_i6.py"
      provides: "monitor_positions public method"
      contains: "def monitor_positions"
    - path: "agents/agent_i6.py"
      provides: "deque-based price history for circuit detection"
      contains: "deque(maxlen=3)"
  key_links:
    - from: "agents/agent_i6.py"
      to: "execution/portfolio.py"
      via: "portfolio.sell(), portfolio.partial_exit(), portfolio.update_stop_loss()"
      pattern: "portfolio\\.sell|portfolio\\.partial_exit|portfolio\\.update_stop_loss"
    - from: "agents/agent_i6.py"
      to: "agents/models.py (WatchlistEntry)"
      via: "watchlist_map[symbol] to read atr, stop_loss, target, strategy"
      pattern: "watchlist_map\\.get"
---

<objective>
Build `agents/agent_i6.py` — the stateful position monitor called by AgentI4 at the start of every polling cycle.

Purpose: AgentI6 enforces all exit logic for open positions — circuit detection, hard SL/target exits, partial exit at 1:1 R:R (GAP_AND_GO and ORB_BREAKOUT only), and trailing SL updates. It is a pure synchronous class (no async) that observes prices and delegates all financial mutations to PaperPortfolio.

Output: `agents/agent_i6.py` with `class AgentI6`, `monitor_positions()` public method, deque-based circuit detection, and per-strategy exit logic matching all 18 locked decisions from 04B-CONTEXT.md.
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
<!-- Contracts the executor must implement against. Extracted from planning context. -->

From agents/models.py (WatchlistEntry — Phase 4a D-13):
```python
@dataclass
class WatchlistEntry:
    symbol: str
    sector: str
    gap_pct: float
    gap_score: float
    strategy: str         # "GAP_AND_GO" | "ORB_BREAKOUT" | "GAP_FILL" | "VWAP_RECLAIM"
    entry_trigger: float
    stop_loss: float      # original stop_loss from Phase 4a (used for risk calculation)
    target: float
    rr_ratio: float
    catalyst_type: str
    atr: float
```

From execution/portfolio.py (PaperPortfolio — Phase 3 D-01, D-04):
```python
def get_portfolio_summary(self) -> dict:
    # Returns:
    # {
    #   "capital": float,
    #   "positions": [
    #     {"symbol": str, "entry_price": float, "qty": int, "stop_loss": float,
    #      "target": float, "strategy": str, "entry_time": str, "partial_exited": bool}
    #   ],
    #   "daily_pnl": float,
    #   "is_halted": bool,
    #   "trade_count": int
    # }

def sell(self, symbol: str, price: float, reason: str = "") -> bool: ...
def partial_exit(self, symbol: str, fraction: float) -> bool: ...
    # fraction=0.5 means exit 50% of qty
def update_stop_loss(self, symbol: str, new_sl: float) -> bool: ...
```

AgentI6 public interface (required per D-05, D-06, D-10):
```python
class AgentI6:
    def __init__(self) -> None: ...
    def monitor_positions(
        self,
        portfolio,            # PaperPortfolio instance
        watchlist_map: dict,  # dict[str, WatchlistEntry]
        current_prices: dict, # dict[str, pd.DataFrame] — keyed by symbol, value is ohlcv df
        current_time,         # datetime.datetime (IST-aware)
        circuit_set: set,     # shared set[str] from AgentI4 (D-10)
    ) -> list[str]: ...       # returns list of action strings for logging
```
</interfaces>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement AgentI6 class with circuit detection and hard exit logic</name>
  <files>agents/agent_i6.py</files>
  <read_first>
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-05, D-06, D-08, D-09, D-10 (circuit detection rules and watchlist_map contract)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — Pattern 3 (deque circuit detection), PaperPortfolio Integration Map, Anti-Patterns section
    - .planning/phases/04A-pre-market-agents/04A-CONTEXT.md — D-13 (WatchlistEntry dataclass fields)
    - .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md — D-01 (positions table schema, partial_exited bool), D-04 (write-through methods)
  </read_first>
  <behavior>
    - Test: _check_circuit with 3 identical prices returns True and adds to circuit_set
    - Test: _check_circuit with non-identical prices (e.g., [1500, 1502, 1501]) returns False
    - Test: _check_circuit with fewer than 3 prices returns False
    - Test: monitor_positions with price <= stop_loss calls portfolio.sell(symbol, price, reason="SL_HIT")
    - Test: monitor_positions with price >= target calls portfolio.sell(symbol, price, reason="TARGET_HIT")
    - Test: symbol already in circuit_set is skipped entirely (no sell, no update_stop_loss call)
    - Test: missing price (current_prices dict has no data for symbol) is skipped silently
  </behavior>
  <action>
    Create `agents/agent_i6.py` with `class AgentI6`. Implement `__init__` initializing `self._price_history: dict[str, deque]` as empty dict (deque instances created lazily per D-08).

    Implement private `_check_circuit(self, symbol: str, current_price: float, circuit_set: set) -> bool`. Uses `deque(maxlen=3)` from `collections`. Appends current_price to `self._price_history[symbol]`, checks `len(d) == 3 and len(set(d)) == 1`. On True: logs `WARNING: POSSIBLE_CIRCUIT detected for {symbol} — skipping for remainder of session` and calls `circuit_set.add(symbol)`. Returns bool.

    Implement `monitor_positions(self, portfolio, watchlist_map, current_prices, current_time, circuit_set) -> list[str]`. Per position from `portfolio.get_portfolio_summary()["positions"]`:
    - Extract `current_price` from `current_prices.get(sym)` — get the last row's Close value from the DataFrame; if the DataFrame is empty or None, skip the symbol with `continue`.
    - Skip if `sym in circuit_set` immediately (per D-09).
    - Call `self._check_circuit(sym, current_price, circuit_set)`; if True, `continue` (per D-09, skip further checks this cycle).
    - Hard exit: `if price <= pos["stop_loss"]: portfolio.sell(sym, price, reason="SL_HIT")` then `continue`.
    - Hard exit: `if price >= pos["target"]: portfolio.sell(sym, price, reason="TARGET_HIT")` then `continue`.

    Log each action with colorlog logger (`logger = setup_logger(__name__)`). Import pattern: `from config import config`, `from utils.logger import setup_logger`. Module-level `logger` only — no per-call logger instantiation. Return list of action strings for caller logging.

    Note on price extraction from candles_map: `current_prices` is `dict[str, pd.DataFrame]`. To get last close: `df = current_prices.get(sym, pd.DataFrame()); if df.empty: continue; price = float(df["Close"].iloc[-1])`.
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i6.py::test_circuit_detection tests/test_agent_i6.py::test_hard_exits -x -q</automated>
  </verify>
  <done>
    agents/agent_i6.py exists with class AgentI6. _check_circuit returns True on 3 identical prices and adds to circuit_set. Hard SL and target exits call portfolio.sell() with correct reason strings. Circuit-flagged symbols are skipped. Tests pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement partial exit and trailing SL logic per strategy</name>
  <files>agents/agent_i6.py</files>
  <read_first>
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-11 (partial exit conditions), D-12 (GAP_FILL/VWAP_RECLAIM hold for full target), D-13 (GAP_AND_GO trailing SL), D-14 (ORB_BREAKOUT breakeven SL), D-15 (fixed SL strategies)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — "Verified: Partial Exit + ORB Breakeven Trailing SL" code example, Pitfall 2 (entry_price vs entry_trigger)
    - agents/agent_i6.py — Task 1 implementation (add to existing monitor_positions method)
  </read_first>
  <behavior>
    - Test (GAP_AND_GO): price >= entry_price + risk and not partial_exited → portfolio.partial_exit(symbol, 0.5) called
    - Test (ORB_BREAKOUT): price >= entry_price + risk and not partial_exited → portfolio.partial_exit(symbol, 0.5) called
    - Test (GAP_FILL): price >= entry_price + risk → partial_exit NOT called (strategy holds full position)
    - Test (VWAP_RECLAIM): price >= entry_price + risk → partial_exit NOT called
    - Test (GAP_AND_GO trailing): price >= entry_price + atr → portfolio.update_stop_loss called with current_price - 0.75 * atr; if new_sl <= current_sl, update_stop_loss NOT called (SL never goes down)
    - Test (ORB_BREAKOUT breakeven): partial_exited == True and entry_price > pos["stop_loss"] → portfolio.update_stop_loss(symbol, entry_price) called
    - Test (GAP_FILL): update_stop_loss never called regardless of price movement (fixed SL per D-15)
    - Test (VWAP_RECLAIM): update_stop_loss never called (fixed SL per D-15)
  </behavior>
  <action>
    Extend `monitor_positions` in `agents/agent_i6.py` — add partial exit and trailing SL logic after the hard exit checks (within the same per-position loop).

    For each position, after hard exit checks:

    PARTIAL EXIT (per D-11, D-12):
    - Compute `risk = pos["entry_price"] - watchlist_entry.stop_loss` (original stop_loss from WatchlistEntry, NOT current pos["stop_loss"]).
    - `partial_exit_threshold = pos["entry_price"] + risk`.
    - `if not pos["partial_exited"] and pos["strategy"] in ("GAP_AND_GO", "ORB_BREAKOUT") and current_price >= partial_exit_threshold: portfolio.partial_exit(sym, 0.5)`.
    - GAP_FILL and VWAP_RECLAIM: no partial exit block at all.

    TRAILING SL (per D-13, D-14, D-15):
    - `if pos["strategy"] == "GAP_AND_GO"`: get `atr` from `watchlist_map.get(sym)`. If atr and `current_price >= pos["entry_price"] + atr`: `new_sl = current_price - 0.75 * atr`; `if new_sl > pos["stop_loss"]: portfolio.update_stop_loss(sym, new_sl)`.
    - `if pos["strategy"] == "ORB_BREAKOUT" and pos["partial_exited"]`: if `pos["entry_price"] > pos["stop_loss"]: portfolio.update_stop_loss(sym, pos["entry_price"])`.
    - GAP_FILL and VWAP_RECLAIM: no trailing SL block (fixed SL per D-15).

    Defensive: if `watchlist_map.get(sym)` returns None (symbol bought but no longer in map), skip trailing SL for that symbol and log WARNING.
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i6.py -x -q</automated>
  </verify>
  <done>
    All 8 test behaviors pass. Partial exit fires only for GAP_AND_GO and ORB_BREAKOUT. GAP_AND_GO trailing SL trails upward only. ORB_BREAKOUT SL moves to breakeven after partial exit. GAP_FILL and VWAP_RECLAIM have no trailing SL calls. Full pytest suite for test_agent_i6.py exits 0.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| yfinance data → AgentI6 | Price data from batch download; may contain NaN, empty DataFrame, or stale candle |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04B-01 | Tampering | current_prices dict (candles from yfinance) | mitigate | Check `df.empty` before extracting Close price; NaN coercion via `float()` raises ValueError — wrap in try/except |
| T-04B-02 | Denial of Service | Unhandled exception in monitor_positions | mitigate | Wrap per-position block in try/except; log error and continue to next position |
| T-04B-03 | Information Disclosure | circuit_set shared reference mutation | accept | Intentional design per D-10; both AgentI4 and AgentI6 share the same set object |
| T-04B-SC | Tampering | npm/pip/cargo installs | accept | No new package installs in this plan — all stdlib/existing dependencies |
</threat_model>

<verification>
## Phase-Level Checks

```bash
# All agent_i6 tests pass
python -m pytest tests/test_agent_i6.py -x -q

# AgentI6 class exists and is importable
python -c "from agents.agent_i6 import AgentI6; a = AgentI6(); print('OK')"

# No ta library imports
python -c "import ast, sys; src=open('agents/agent_i6.py').read(); assert 'import ta' not in src; print('no ta import — OK')"

# Deque used for circuit detection
python -c "import ast; src=open('agents/agent_i6.py').read(); assert 'deque' in src; print('deque found — OK')"
```
</verification>

<success_criteria>
- `agents/agent_i6.py` exists and contains `class AgentI6`
- `python -m pytest tests/test_agent_i6.py -x -q` exits 0 with all test cases green
- `from agents.agent_i6 import AgentI6` imports without error
- `deque(maxlen=3)` is used for price tracking (grep confirms `deque` in agent_i6.py)
- No `ta` imports in agent_i6.py
- All four strategies' exit rules are implemented: GAP_AND_GO (partial + trailing), ORB_BREAKOUT (partial + breakeven), GAP_FILL (fixed SL, hold full), VWAP_RECLAIM (fixed SL, hold full)
- POSSIBLE_CIRCUIT detection: 3 identical prices → log WARNING, add to circuit_set, skip symbol
</success_criteria>

<output>
Create `.planning/phases/04B-market-session-agents/04B-01-SUMMARY.md` when done
</output>
