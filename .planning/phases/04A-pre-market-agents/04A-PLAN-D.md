---
wave: 4
plan_id: "04A-PLAN-D"
phase: "04A"
phase_name: "Pre-Market Agents"
objective: "Create agents/agent_i3.py — strategy assignment + ATR-based price levels + R:R filter → top 10 watchlist"
depends_on:
  - "04A-PLAN-C"
files_modified:
  - agents/agent_i3.py
autonomous: true
requirements_addressed:
  - AGNT-07
  - AGNT-08
must_haves:
  truths:
    - "Strategy assignment uses deterministic rule table — no Gemini call"
    - "GAP_AND_GO assigned when abs(gap_pct) > 3.0 AND bias == BULLISH"
    - "ORB_BREAKOUT assigned when abs(gap_pct) > 2.0 AND bias == NEUTRAL"
    - "GAP_FILL assigned when 1.5 <= abs(gap_pct) <= 3.0 (any bias)"
    - "VWAP_RECLAIM assigned when abs(gap_pct) < 2.0 (any bias)"
    - "Candidates where ATR fetch fails are skipped (cannot compute price levels)"
    - "Candidates with rr_ratio < config.MIN_RR_RATIO (1.5) are excluded from watchlist"
    - "watchlist_ready.set() called after run() completes"
    - "AgentI3.run() is a coroutine, never raises"
    - "Returns top 10 by gap_score descending"
---

# Phase 4a Plan D: AgentI3 (Strategy Assignment + Watchlist)

## Tasks

### Task 1: Create agents/agent_i3.py — ATR fetch + strategy rule table

<read_first>
- .planning/phases/04A-pre-market-agents/04A-CONTEXT.md (D-09 — strategy rule table, D-10 — ATR fetch, D-11 — price level formulas, D-12 — R:R filter, D-13 — WatchlistEntry, D-14 — watchlist_ready Event)
- .planning/REQUIREMENTS.md (AGNT-07, AGNT-08)
- agents/models.py (GapCandidate, WatchlistEntry, MarketBias)
- data/market_data.py (MarketDataFetcher.get_atr() return type — float or None)
- config.py (config.MIN_RR_RATIO, config.MAX_WATCHLIST_SIZE)
</read_first>

<action>
Create `agents/agent_i3.py`:

**Module-level:**
- `logger = setup_logger(__name__)`
- `fetcher = MarketDataFetcher()` — module-level instance

**`async def run(candidates: list[GapCandidate], bias: MarketBias, watchlist_ready: asyncio.Event | None = None) -> list[WatchlistEntry]`**:
1. `entries = await asyncio.to_thread(_build_watchlist, candidates, bias)`
2. Log INFO: `"📋 AgentI3 watchlist: {len(entries)} entries"`
3. If `watchlist_ready is not None` → `watchlist_ready.set()`
4. Return entries

**`def _build_watchlist(candidates: list[GapCandidate], bias: MarketBias) -> list[WatchlistEntry]`** — sync inner:
1. For each candidate in `candidates`:
   a. Fetch ATR: `atr = fetcher.get_atr(candidate.symbol)` — returns float or None
   b. If `atr is None` or `atr <= 0` → log WARNING f"{symbol}: ATR unavailable — skipping" → continue
   c. Assign strategy: call `_assign_strategy(candidate, bias)`
   d. Compute price levels: call `_compute_levels(candidate, strategy, atr)` → returns dict
   e. Compute R:R: `rr_ratio = (target - entry_trigger) / (entry_trigger - stop_loss)`
   f. If `rr_ratio < config.MIN_RR_RATIO` → log DEBUG f"{symbol}: R:R {rr_ratio:.2f} < {config.MIN_RR_RATIO} — skipped" → continue
   g. Append `WatchlistEntry(symbol, sector, gap_pct, gap_score, strategy, entry_trigger, stop_loss, target, round(rr_ratio, 2), catalyst_type, atr)` to results
2. Sort results by `gap_score` descending
3. Return top `config.MAX_WATCHLIST_SIZE` (10) entries

**`def _assign_strategy(candidate: GapCandidate, bias: MarketBias) -> str`** — rule table (priority order):
1. `if abs(candidate.gap_pct) > 3.0 and bias.bias == "BULLISH"` → return `"GAP_AND_GO"`
2. `elif abs(candidate.gap_pct) > 2.0 and bias.bias == "NEUTRAL"` → return `"ORB_BREAKOUT"`
3. `elif 1.5 <= abs(candidate.gap_pct) <= 3.0` → return `"GAP_FILL"`
4. `elif abs(candidate.gap_pct) < 2.0` → return `"VWAP_RECLAIM"`
5. else → return `"VWAP_RECLAIM"` (fallback — should not reach here with 1.5-8% filter)
</action>

<acceptance_criteria>
- `agents/agent_i3.py` imports without error
- `run()` is a coroutine
- `_assign_strategy`: gap_pct=5.0 + BULLISH → "GAP_AND_GO"
- `_assign_strategy`: gap_pct=3.0 + NEUTRAL → "ORB_BREAKOUT"
- `_assign_strategy`: gap_pct=2.0 + BULLISH → "GAP_FILL" (rule 1 requires > 3.0 to be GAP_AND_GO)
- `_assign_strategy`: gap_pct=1.5 + NEUTRAL → "GAP_FILL" (rule 2 requires > 2.0 for ORB_BREAKOUT)
- `_assign_strategy`: gap_pct=1.6 + BULLISH → "GAP_FILL"
- Candidate where get_atr() returns None is NOT in watchlist output
- Candidate with rr_ratio < 1.5 is NOT in watchlist output
- watchlist_ready.set() called after run() completes (when not None)
- watchlist_ready=None → no error (optional parameter)
- Output sorted by gap_score descending
- Output length ≤ config.MAX_WATCHLIST_SIZE (10)
- `run([])` returns `[]`
</acceptance_criteria>

---

### Task 2: Implement _compute_levels() with per-strategy formulas

<read_first>
- .planning/phases/04A-pre-market-agents/04A-CONTEXT.md (D-11 — exact price level table for all 4 strategies)
- agents/models.py (GapCandidate fields: premarket_price, prev_close, gap_pct)
</read_first>

<action>
Add `_compute_levels(candidate: GapCandidate, strategy: str, atr: float) -> dict` to `agents/agent_i3.py`:

**GAP_AND_GO**:
- `entry_trigger = candidate.premarket_price * 1.002`
- `stop_loss = entry_trigger - (1.5 * atr)`
- `target = entry_trigger + (2.25 * atr)`

**GAP_FILL**:
- `entry_trigger = candidate.premarket_price * 0.998`
- `stop_loss = entry_trigger - (1.0 * atr)`
- `target = candidate.prev_close`  (fill-to-prev-close target)

**ORB_BREAKOUT**:
- `entry_trigger = candidate.premarket_price * 1.005`  (placeholder; AgentI4 overrides with actual ORB high at 09:30)
- `stop_loss = candidate.prev_close - (0.5 * atr)`  (near prev-close level)
- `target = entry_trigger + (2.0 * atr)`

**VWAP_RECLAIM**:
- `entry_trigger = candidate.premarket_price * 1.001`
- `stop_loss = entry_trigger - (1.0 * atr)`
- `target = entry_trigger + (1.5 * atr)`

All price values: `round(value, 2)`

Returns: `{"entry_trigger": float, "stop_loss": float, "target": float}`
</action>

<acceptance_criteria>
- `_compute_levels` for GAP_AND_GO with premarket=2000, atr=50: entry=2004.0, stop=1929.0, target=2116.5
- `_compute_levels` for VWAP_RECLAIM with premarket=500, atr=10: entry=500.5, stop=490.5, target=515.5, rr_ratio=1.5 exactly
- `_compute_levels` for GAP_FILL with premarket=1050, prev_close=1000, atr=20: entry=1048.95 (≈1050*0.998), stop=1028.95, target=1000.0
  - rr_ratio for GAP_FILL = (1000 - 1048.95) / (1048.95 - 1028.95) = -48.95 / 20 < 0 → this candidate FAILS R:R filter and is excluded
  - This is correct behavior: GAP_FILL on a positive-gap stock (prev_close < premarket_price) fails R:R because target < entry
- `_compute_levels` for GAP_FILL with negative-gap stock (premarket < prev_close): entry_trigger < prev_close → rr_ratio > 0, may pass filter
- All returned prices rounded to 2 decimal places
</acceptance_criteria>

---

## Verification

```bash
python -c "
from agents.agent_i3 import _assign_strategy, _compute_levels
from agents.models import GapCandidate, MarketBias

# Strategy assignment tests
bias_bull = MarketBias(bias='BULLISH', bias_strength=0.8, gift_nifty_gap_pct=0.5, valid_strategies=['GAP_AND_GO'], confidence=0.9)
bias_neut = MarketBias(bias='NEUTRAL', bias_strength=0.3, gift_nifty_gap_pct=0.0, valid_strategies=['GAP_AND_GO', 'ORB_BREAKOUT', 'GAP_FILL', 'VWAP_RECLAIM'], confidence=0.4)

c1 = GapCandidate('A.NS', 'T', 2000.0, 2100.0, 5.0, 1000000, 15.0)
assert _assign_strategy(c1, bias_bull) == 'GAP_AND_GO', f'Expected GAP_AND_GO: {_assign_strategy(c1, bias_bull)}'

c2 = GapCandidate('B.NS', 'T', 2000.0, 2070.0, 3.5, 1000000, 7.0)
assert _assign_strategy(c2, bias_neut) == 'ORB_BREAKOUT', f'Expected ORB_BREAKOUT: {_assign_strategy(c2, bias_neut)}'

c3 = GapCandidate('C.NS', 'T', 1000.0, 1025.0, 2.5, 800000, 4.0)
assert _assign_strategy(c3, bias_bull) == 'GAP_FILL', f'Expected GAP_FILL: {_assign_strategy(c3, bias_bull)}'

c4 = GapCandidate('D.NS', 'T', 500.0, 508.0, 1.6, 600000, 1.92)
assert _assign_strategy(c4, bias_neut) == 'GAP_FILL', f'Expected GAP_FILL: {_assign_strategy(c4, bias_neut)}'

# Price level tests
levels = _compute_levels(c1, 'GAP_AND_GO', 50.0)
entry = levels['entry_trigger']
stop = levels['stop_loss']
target = levels['target']
assert abs(entry - 2100 * 1.002) < 0.01, f'entry_trigger wrong: {entry}'
assert abs(stop - (entry - 1.5 * 50)) < 0.01, f'stop_loss wrong: {stop}'
assert abs(target - (entry + 2.25 * 50)) < 0.01, f'target wrong: {target}'
rr = (target - entry) / (entry - stop)
assert abs(rr - 1.5) < 0.01, f'R:R should be 1.5 for GAP_AND_GO: {rr}'

levels_vwap = _compute_levels(c4, 'VWAP_RECLAIM', 10.0)
entry_v = levels_vwap['entry_trigger']
target_v = levels_vwap['target']
stop_v = levels_vwap['stop_loss']
rr_v = (target_v - entry_v) / (entry_v - stop_v)
assert abs(rr_v - 1.5) < 0.01, f'VWAP_RECLAIM R:R should be 1.5: {rr_v}'

print('agent_i3.py: all assertions passed')
"

python -c "
import asyncio
from agents.agent_i3 import run
from agents.models import GapCandidate, MarketBias, WatchlistEntry

# run([]) returns []
bias = MarketBias(bias='NEUTRAL', bias_strength=0.3, gift_nifty_gap_pct=0.0, valid_strategies=['GAP_AND_GO'], confidence=0.4)
result = asyncio.run(run([], bias))
assert result == [], f'Empty input should return []: {result}'
print('run([]) returns [] — passed')

# watchlist_ready.set() test
event = asyncio.Event()
result = asyncio.run(run([], bias, event))
assert event.is_set(), 'watchlist_ready.set() should be called after run()'
print('watchlist_ready.set() called — passed')
"
```
