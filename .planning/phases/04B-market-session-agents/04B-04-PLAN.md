---
phase: 04B-market-session-agents
plan: 04
type: execute
wave: 2
depends_on:
  - 04B-01
  - 04B-02
  - 04B-03
files_modified:
  - tests/conftest.py
  - tests/test_agent_i4.py
  - tests/test_agent_i6.py
autonomous: true
requirements:
  - AGNT-09
  - AGNT-10
  - AGNT-11
  - AGNT-12

must_haves:
  truths:
    - "pytest suite covers all 8 behaviors mapped in AGNT-09 through AGNT-12"
    - "make_candles() fixture in conftest.py builds synthetic IST-aware OHLCV DataFrames — no live market data needed"
    - "mock PaperPortfolio (MagicMock) verifies sell(), partial_exit(), update_stop_loss() call signatures"
    - "AGNT-09 test: loop exits at 15:15, force_squareoff_all called"
    - "AGNT-10 tests: time gate blocks buy before 09:30 and after 14:00; all four strategy signals trigger buy on correct candle"
    - "AGNT-11 test: force_squareoff_all called twice — portfolio.sell called only once per position"
    - "AGNT-12 tests: partial exit at 1:1 R:R for GAP_AND_GO and ORB_BREAKOUT; no partial exit for GAP_FILL/VWAP_RECLAIM; GAP_AND_GO trailing SL; ORB breakeven SL; circuit detection on 3 identical prices"
    - "All tests use synthetic candles — no yfinance network calls during test run"
  artifacts:
    - path: "tests/conftest.py"
      provides: "make_candles() fixture and mock_portfolio factory"
      contains: "def make_candles"
    - path: "tests/test_agent_i4.py"
      provides: "AGNT-09, AGNT-10, AGNT-11 test cases"
      contains: "test_loop_exits_at_1515"
    - path: "tests/test_agent_i6.py"
      provides: "AGNT-12 test cases"
      contains: "test_partial_exit"
  key_links:
    - from: "tests/test_agent_i4.py"
      to: "agents/agent_i4.py"
      via: "imports AgentI4; injects synthetic candles and mock portfolio"
      pattern: "from agents\\.agent_i4 import AgentI4"
    - from: "tests/test_agent_i6.py"
      to: "agents/agent_i6.py"
      via: "imports AgentI6; injects mock portfolio via MagicMock"
      pattern: "from agents\\.agent_i6 import AgentI6"
---

<objective>
Write the complete pytest test suites for `agents/agent_i4.py` and `agents/agent_i6.py`, plus the shared `conftest.py` with synthetic candle and mock portfolio fixtures.

Purpose: Plans 01–03 produced runnable agents but tests were written alongside them (TDD). This plan adds the remaining tests for the 8 behaviors mapped in the RESEARCH.md validation architecture, ensures all AGNT-09 through AGNT-12 requirements are verifiably covered, and validates the full phase by running the complete suite.

Output: `tests/conftest.py`, `tests/test_agent_i4.py`, `tests/test_agent_i6.py` — all passing with `python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q`.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/phases/04B-market-session-agents/04B-CONTEXT.md
@.planning/phases/04B-market-session-agents/04B-RESEARCH.md
</context>

<interfaces>
<!-- Key patterns from RESEARCH.md the test author needs. -->

Synthetic candle builder pattern (from RESEARCH.md "Validation Architecture"):
```python
import pandas as pd, datetime, pytz
IST = pytz.timezone("Asia/Kolkata")

def make_candles(prices: list[float], start_hour: int = 9, start_min: int = 15) -> pd.DataFrame:
    """Build a 5-minute OHLCV DataFrame starting at IST time."""
    base = datetime.datetime.now(IST).replace(
        hour=start_hour, minute=start_min, second=0, microsecond=0
    )
    rows = [{"Open": p, "High": p + 2, "Low": p - 2,
             "Close": p, "Adj Close": p, "Volume": 500_000}
            for p in prices]
    index = [base + datetime.timedelta(minutes=5*i) for i in range(len(prices))]
    return pd.DataFrame(rows, index=index)
```

Mock portfolio pattern (from RESEARCH.md "Synthetic Candle Test Strategy"):
```python
from unittest.mock import MagicMock
def mock_portfolio(positions=None):
    p = MagicMock()
    p.get_portfolio_summary.return_value = {
        "capital": 100000.0,
        "positions": positions or [],
        "daily_pnl": 0.0,
        "is_halted": False,
        "trade_count": 0,
    }
    p.buy.return_value = True
    p.sell.return_value = True
    p.partial_exit.return_value = True
    p.update_stop_loss.return_value = True
    return p
```

WatchlistEntry factory for tests:
```python
from agents.models import WatchlistEntry   # or from agents.agent_i3 import WatchlistEntry
def make_entry(symbol, strategy, entry_trigger, stop_loss, target, atr=10.0):
    return WatchlistEntry(
        symbol=symbol, sector="Test", gap_pct=2.0, gap_score=3.0,
        strategy=strategy, entry_trigger=entry_trigger,
        stop_loss=stop_loss, target=target, rr_ratio=1.5,
        catalyst_type="EARNINGS", atr=atr
    )
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Create conftest.py with shared fixtures and write AgentI6 test suite</name>
  <files>tests/conftest.py, tests/test_agent_i6.py</files>
  <read_first>
    - agents/agent_i6.py — final implementation from Plans 01 (both tasks)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — §"Validation Architecture" (test map table, synthetic candle pattern, mock portfolio pattern)
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-08, D-09 (circuit), D-11, D-12 (partial exit), D-13, D-14, D-15 (trailing SL)
  </read_first>
  <action>
    Create `tests/conftest.py` with:
    - `make_candles(prices, start_hour=9, start_min=15)` function as specified in interfaces above. Export as pytest fixture using `@pytest.fixture` AND as a plain function (so both `make_candles()` and `make_candles` fixture work).
    - `mock_portfolio(positions=None)` function returning a configured MagicMock.
    - `make_entry(symbol, strategy, entry_trigger, stop_loss, target, atr=10.0)` function returning WatchlistEntry.
    - Import guard: `from agents.models import WatchlistEntry` (fall back to `from agents.agent_i3 import WatchlistEntry` if models.py does not exist — check which Phase 4a file defines it).

    Create `tests/test_agent_i6.py` with the following test functions. Each test is self-contained with no live market data:

    `test_circuit_detection()`:
    - Create AgentI6 instance. Create a circuit_set = set().
    - Build candles_map with 3 identical prices for "RELIANCE.NS": make_candles([1500.0, 1500.0, 1500.0]).
    - Build position list with one open position for RELIANCE.NS (entry_price=1480, stop_loss=1465, target=1510, strategy="GAP_AND_GO", partial_exited=False).
    - Call monitor_positions; verify "RELIANCE.NS" in circuit_set after call.
    - Call monitor_positions again with same data; verify portfolio.sell NOT called (skip on circuit_set membership).

    `test_hard_exits()`:
    - SL hit: price=1460, stop_loss=1465 → portfolio.sell("RELIANCE.NS", 1460, reason="SL_HIT") called.
    - Target hit: price=1515, target=1510 → portfolio.sell("RELIANCE.NS", 1515, reason="TARGET_HIT") called.
    - Normal price: price=1490, not at SL or target → portfolio.sell NOT called.

    `test_partial_exit()`:
    - GAP_AND_GO: entry_price=1480, original_stop_loss=1465, risk=15, threshold=1495. Price=1496, partial_exited=False → portfolio.partial_exit("RELIANCE.NS", 0.5) called.
    - GAP_FILL: same numeric values but strategy="GAP_FILL" → partial_exit NOT called.
    - VWAP_RECLAIM: strategy="VWAP_RECLAIM" → partial_exit NOT called.
    - Already partial exited (partial_exited=True) → partial_exit NOT called again.

    `test_trailing_sl_gap_and_go()`:
    - entry_price=1480, atr=20. Profit threshold = entry_price + atr = 1500.
    - Price=1505 (>= 1500): new_sl = 1505 - 0.75*20 = 1490. Current SL=1465 → portfolio.update_stop_loss("RELIANCE.NS", 1490) called.
    - Price=1498 (< 1500): trailing SL not triggered → update_stop_loss NOT called.
    - new_sl=1485 but current SL=1490 (new < current): update_stop_loss NOT called (SL only moves up).

    `test_orb_breakeven_sl()`:
    - strategy="ORB_BREAKOUT", entry_price=1480, current stop_loss=1465, partial_exited=True.
    - entry_price (1480) > current_sl (1465) → portfolio.update_stop_loss("RELIANCE.NS", 1480) called.
    - If current stop_loss already at entry_price (1480): update_stop_loss NOT called.

    `test_gap_fill_fixed_sl()`:
    - strategy="GAP_FILL", any price above entry_price → update_stop_loss NOT called.
    `test_vwap_reclaim_fixed_sl()`:
    - strategy="VWAP_RECLAIM", any price → update_stop_loss NOT called.
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i6.py -x -q</automated>
  </verify>
  <done>
    tests/conftest.py exists with make_candles, mock_portfolio, make_entry. tests/test_agent_i6.py passes all 7 test functions. `python -m pytest tests/test_agent_i6.py -x -q` exits 0.
  </done>
</task>

<task type="auto">
  <name>Task 2: Write AgentI4 test suite covering AGNT-09, AGNT-10, AGNT-11 and run full phase suite</name>
  <files>tests/test_agent_i4.py</files>
  <read_first>
    - agents/agent_i4.py — final implementation from Plans 02 and 03 (all tasks)
    - .planning/phases/04B-market-session-agents/04B-RESEARCH.md — §"Validation Architecture" test map (AGNT-09, AGNT-10, AGNT-11 rows)
    - .planning/phases/04B-market-session-agents/04B-CONTEXT.md — D-01 (four signals), D-04 (time gates), D-17 (squaredoff)
    - tests/conftest.py — make_candles, mock_portfolio, make_entry from Task 1
  </read_first>
  <action>
    Create `tests/test_agent_i4.py` with the following test functions:

    `test_init()`:
    - AgentI4([entry1, entry2]) → self.watchlist_map == {"SYM1": entry1, "SYM2": entry2}.
    - self._squaredoff == False, self._orb_set == False, self.circuit_set == set().
    - isinstance(self.monitor, AgentI6) is True.

    `test_fetch_batch_empty()`:
    - AgentI4([])._fetch_batch([]) == {}.

    `test_fetch_batch_single_symbol()` (mock yf.download):
    - Patch `yfinance.download` to return a flat-Index DataFrame (no MultiIndex).
    - _fetch_batch(["RELIANCE.NS"]) → {"RELIANCE.NS": <that DataFrame>} (no .xs() attempted).

    `test_fetch_batch_multi_symbol()` (mock yf.download):
    - Patch `yfinance.download` to return a MultiIndex DataFrame with two symbols.
    - _fetch_batch(["RELIANCE.NS", "TCS.NS"]) → both symbols extracted via .xs().

    `test_orb_override()`:
    - Create AgentI4 with one ORB_BREAKOUT entry (entry_trigger=1050.0) and one GAP_AND_GO entry.
    - Build candles_map: 3 candles with highs [1020, 1030, 1045] for the ORB symbol.
    - current_time = 09:30 IST. Call _maybe_apply_orb_override.
    - Assert ORB_BREAKOUT entry_trigger updated to Indicators.orb() return value.
    - Assert GAP_AND_GO entry_trigger unchanged.
    - Call _maybe_apply_orb_override again — assert entry_trigger NOT changed a second time (_orb_set=True).

    `test_squareoff_idempotent()`:
    - portfolio has one open position "RELIANCE.NS" at entry_price=1480.
    - Call force_squareoff_all(portfolio, {}) → portfolio.sell called once.
    - Call force_squareoff_all(portfolio, {}) again → portfolio.sell NOT called again (total sell calls == 1).

    `test_loop_exits_at_1515()` (async test using pytest-asyncio or asyncio.run):
    - Use asyncio.run() to run a minimal version: patch asyncio.sleep to be a no-op, inject a mock time that returns 15:15 on first call.
    - Verify run() returns after the loop and calls force_squareoff_all.
    - Note: use `unittest.mock.patch("agents.agent_i4.datetime")` to control current time.

    `test_entry_time_gates()`:
    - Build candles_map with price that satisfies GAP_AND_GO signal.
    - current_time = 09:15 IST (before entry_start=09:30) → portfolio.buy NOT called.
    - current_time = 14:30 IST (after entry_cutoff=14:00) → portfolio.buy NOT called.
    - current_time = 10:00 IST (within window) → portfolio.buy called.

    `test_gap_and_go_signal()`, `test_gap_fill_signal()`, `test_orb_breakout_signal()`, `test_vwap_reclaim_signal()`:
    - Each test: one WatchlistEntry with the relevant strategy, current_time=10:00 IST.
    - Price meets signal condition → portfolio.buy called with correct symbol, strategy.
    - Price does NOT meet signal condition → portfolio.buy NOT called.
    - After buy, symbol removed from watchlist_map.

    After writing all tests, run the full phase suite:
    `python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q`

    All tests must pass. Fix any test/implementation mismatches found. Document root cause and fix in SUMMARY.md.
  </action>
  <verify>
    <automated>python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q</automated>
  </verify>
  <done>
    tests/test_agent_i4.py contains test functions for AGNT-09, AGNT-10, AGNT-11. Full suite `python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q` exits 0 with all tests green. No live market data accessed during test run.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Test mocks → production code | MagicMock replaces PaperPortfolio — call assertions must match actual method signatures |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04B-13 | Repudiation | Test stubs masking real integration issues | mitigate | Tests assert on exact method names and arg values per PaperPortfolio API from 03-CONTEXT; verified signatures before writing mocks |
| T-04B-14 | Tampering | Synthetic candle index timezone mismatch | mitigate | make_candles always uses datetime.datetime.now(IST).replace() for IST-aware index; no naive datetimes |
| T-04B-SC | Tampering | npm/pip/cargo installs | accept | No new packages — pytest already available per RESEARCH.md environment table |
</threat_model>

<verification>
## Phase Gate (all four plans complete)

```bash
# Full phase suite — must be green before /gsd:verify-work
python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q

# No live network calls during tests (yfinance must be mocked)
python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q --tb=short 2>&1 | grep -i "yfinance\|network\|timeout" || echo "no network calls — OK"

# agent_i4 and agent_i6 importable
python -c "from agents.agent_i4 import AgentI4; from agents.agent_i6 import AgentI6; print('imports OK')"

# AGNT-09: loop structure check
python -c "src=open('agents/agent_i4.py').read(); assert 'await asyncio.sleep(60)' in src; assert 'watchlist_ready_event.wait()' in src; print('AGNT-09 loop — OK')"

# AGNT-10: all four strategies present
python -c "
src=open('agents/agent_i4.py').read()
for s in ('GAP_AND_GO','GAP_FILL','ORB_BREAKOUT','VWAP_RECLAIM'):
    assert s in src, f'missing: {s}'
print('AGNT-10 strategies — OK')
"

# AGNT-11: squaredoff guard
python -c "src=open('agents/agent_i4.py').read(); assert '_squaredoff' in src; print('AGNT-11 guard — OK')"

# AGNT-12: deque and partial exit
python -c "src=open('agents/agent_i6.py').read(); assert 'deque' in src; assert 'partial_exit' in src; print('AGNT-12 — OK')"
```
</verification>

<success_criteria>
## Multi-Source Coverage Audit

| Source | Item | Covered By |
|--------|------|------------|
| GOAL (Phase 4b) | Signal engine detects entries using all four strategies | 04B-03 Task 2 |
| GOAL (Phase 4b) | Position monitor enforces exits 09:15–15:15 | 04B-01 Tasks 1+2 |
| REQ AGNT-09 | 60s polling loop 09:15–15:15 | 04B-03 Task 1 |
| REQ AGNT-09 | No entries before 09:30 or after 14:00 | 04B-03 Task 2 |
| REQ AGNT-10 | GAP_AND_GO signal fires on correct candle | 04B-03 Task 2 |
| REQ AGNT-10 | GAP_FILL signal fires on correct candle | 04B-03 Task 2 |
| REQ AGNT-10 | ORB_BREAKOUT signal fires on correct candle | 04B-03 Task 2 |
| REQ AGNT-10 | VWAP_RECLAIM signal fires on correct candle | 04B-03 Task 2 |
| REQ AGNT-11 | force_squareoff_all is idempotent | 04B-02 Task 2 |
| REQ AGNT-12 | Partial exit at 1:1 R:R (GAP_AND_GO, ORB_BREAKOUT) | 04B-01 Task 2 |
| REQ AGNT-12 | Trailing SL GAP_AND_GO (0.75 ATR) | 04B-01 Task 2 |
| REQ AGNT-12 | ORB SL moves to breakeven after partial exit | 04B-01 Task 2 |
| REQ AGNT-12 | POSSIBLE_CIRCUIT detection (3 identical prices) | 04B-01 Task 1 |
| RESEARCH | Single-symbol yf.download flat Index branch | 04B-02 Task 1 |
| RESEARCH | ORB override _orb_set one-time guard | 04B-02 Task 2 |
| CONTEXT D-03 | One buy per symbol, remove after success | 04B-03 Task 2 |
| CONTEXT D-06 | watchlist_map passed to AgentI6 | 04B-01 Task 1 |
| CONTEXT D-07 | AgentI6 instantiated inside AgentI4.__init__ | 04B-02 Task 1 |
| CONTEXT D-10 | circuit_set shared reference AgentI4↔AgentI6 | 04B-01 Task 1 |
| CONTEXT D-18 | 0.2s sleep before batch fetch | 04B-02 Task 1 |

- `python -m pytest tests/test_agent_i4.py tests/test_agent_i6.py -x -q` exits 0
- No live network calls during tests
- Both agents importable: `from agents.agent_i4 import AgentI4; from agents.agent_i6 import AgentI6`
</success_criteria>

<output>
Create `.planning/phases/04B-market-session-agents/04B-04-SUMMARY.md` when done
</output>
