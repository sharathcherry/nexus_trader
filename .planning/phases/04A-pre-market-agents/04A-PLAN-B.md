---
wave: 2
plan_id: "04A-PLAN-B"
phase: "04A"
phase_name: "Pre-Market Agents"
objective: "Create agents/agent_i1.py — gap scanner, filters 100-stock universe to top 20 candidates by gap_score"
depends_on:
  - "04A-PLAN-A"
files_modified:
  - agents/agent_i1.py
autonomous: true
requirements_addressed:
  - AGNT-03
  - AGNT-04
must_haves:
  truths:
    - "AgentI1.run() returns list[GapCandidate] sorted by gap_score descending, max 20 entries"
    - "gap_score = abs(gap_pct) * min(prev_volume / 500_000, 3.0)"
    - "Candidates with abs(gap_pct) < 1.5 or abs(gap_pct) > 8.0 are excluded"
    - "Candidates with prev_volume < 500_000 are excluded"
    - "Candidates with premarket_price < 50 or > 5000 are excluded"
    - "0.2s delay between sequential yfinance calls (MarketDataFetcher enforces this)"
    - "If fewer than 3 candidates found after all filters, returns empty list (NO_TRADE_DAY signal)"
    - "AgentI1.run() is a coroutine, never raises"
---

# Phase 4a Plan B: AgentI1 (Gap Scanner)

## Tasks

### Task 1: Create agents/agent_i1.py — fetch loop and raw candidate list

<read_first>
- .planning/phases/04A-pre-market-agents/04A-CONTEXT.md (D-02, D-03, D-04 — gap_score formula, filters, GapCandidate fields)
- .planning/REQUIREMENTS.md (AGNT-03, AGNT-04)
- data/universe.py (get_universe() return format — list of dicts with "symbol" and "sector" keys)
- data/market_data.py (MarketDataFetcher.get_previous_close(), .get_premarket_price() signatures and return types)
- agents/models.py (GapCandidate dataclass fields)
- config.py (config.MIN_GAP_PCT, config.MAX_GAP_PCT, config.MIN_VOLUME, config.MIN_PRICE, config.MAX_PRICE)
</read_first>

<action>
Create `agents/agent_i1.py`:

**Module-level:**
- `logger = setup_logger(__name__)`, `IST = pytz.timezone("Asia/Kolkata")`
- `fetcher = MarketDataFetcher()` — module-level instance

**`async def run() -> list[GapCandidate]`** — main entry point:
1. `return await asyncio.to_thread(_scan_universe)`

**`def _scan_universe() -> list[GapCandidate]`** — sync inner function:
1. `universe = get_universe()` — 100 dicts with "symbol" and "sector"
2. Fetch previous closes for all 100 symbols: `prev_closes = fetcher.get_previous_close([s["symbol"] for s in universe])` — returns `dict[str, float]`
3. For each stock in universe (sequential loop):
   - Skip if symbol not in `prev_closes` or `prev_closes[symbol]` is None/0
   - Call `premarket_price = fetcher.get_premarket_price(symbol)` — returns `float | None`
   - If None → skip
   - Note: `get_premarket_price()` already enforces 0.2s delay internally
4. Compute: `gap_pct = (premarket_price - prev_close) / prev_close * 100`
5. Get previous volume: `prev_volume` must come from `fetcher.get_previous_close()` extended return OR a separate volume fetch. Use `fetcher.get_historical_data(symbol, period="5d")["Volume"].iloc[-2]` for previous day volume. If unavailable → skip.
6. Apply filters:
   - `abs(gap_pct) < config.MIN_GAP_PCT` (1.5) → skip
   - `abs(gap_pct) > config.MAX_GAP_PCT` (8.0) → skip
   - `prev_volume < config.MIN_VOLUME` (500_000) → skip
   - `premarket_price < config.MIN_PRICE` (50) → skip
   - `premarket_price > config.MAX_PRICE` (5000) → skip
7. Compute gap_score: `gap_score = abs(gap_pct) * min(prev_volume / 500_000, 3.0)`
8. Append `GapCandidate(symbol, sector, prev_close, premarket_price, gap_pct, prev_volume, gap_score)` to candidates list
9. After loop: if `len(candidates) < 3` → log WARNING "⚠ Fewer than 3 gap candidates found — NO_TRADE_DAY" → return `[]`
10. Sort by `gap_score` descending, return top 20
11. Log INFO: `"📊 AgentI1 found {len(candidates)} candidates → top {len(result)} selected"`
</action>

<acceptance_criteria>
- `agents/agent_i1.py` imports without error
- `run()` is a coroutine (`asyncio.iscoroutinefunction(run)` returns True)
- Result is a `list[GapCandidate]` (may be empty on NO_TRADE_DAY)
- Result length ≤ 20
- Result is sorted by `gap_score` descending (if non-empty)
- `gap_score = abs(gap_pct) * min(prev_volume / 500_000, 3.0)` formula used — verify: candidate with gap_pct=4.0, prev_volume=1_000_000 has gap_score=8.0
- Candidate with abs(gap_pct)=1.2 is NOT in result (below 1.5% threshold)
- Candidate with prev_volume=400_000 is NOT in result (below 500k threshold)
- Candidate with premarket_price=30.0 is NOT in result (below ₹50 threshold)
- `run()` never raises — all yfinance errors caught and logged
- When fewer than 3 candidates survive filters: returns empty list
- Log line contains "📊 AgentI1 found" on success
- Log WARNING contains "NO_TRADE_DAY" when empty list returned
</acceptance_criteria>

---

### Task 2: Integrate direction filter (bias-aware post-filter)

<read_first>
- .planning/phases/04A-pre-market-agents/04A-CONTEXT.md (D-03 — direction filter, BEARISH treated as NEUTRAL in v1)
- .planning/STATE.md §"Key Decisions Made" — I0+I1 concurrent, direction filter is orchestrator concern
- agents/models.py (MarketBias, GapCandidate — gap_pct sign)
</read_first>

<action>
Add a standalone utility function to `agents/agent_i1.py`:

`def apply_direction_filter(candidates: list[GapCandidate], bias: MarketBias) -> list[GapCandidate]`:
- If `bias.bias == "BULLISH"` → keep only candidates where `gap_pct > 0`
- If `bias.bias == "BEARISH"` → treat as NEUTRAL (v1 long-only — no short selling)
- If `bias.bias == "NEUTRAL"` → keep all candidates (both gap-up and gap-down)
- Return filtered list

This function is NOT called by `run()` — it is called by the Phase 5 orchestrator AFTER `asyncio.gather(i0_run, i1_run)` returns both results.

Log INFO when called: `"🔀 Direction filter [{bias.bias}]: {len(input)} → {len(output)} candidates"`
</action>

<acceptance_criteria>
- `apply_direction_filter` is importable from `agents.agent_i1`
- BULLISH bias: only positive gap_pct candidates returned
- BEARISH bias: all candidates returned (treated as NEUTRAL)
- NEUTRAL bias: all candidates returned unchanged
- Empty input → empty output
- `apply_direction_filter` is a plain sync function (not async)
</acceptance_criteria>

---

## Verification

```bash
python -c "
from agents.agent_i1 import apply_direction_filter
from agents.models import GapCandidate, MarketBias

# Create test candidates
positive = GapCandidate('A.NS', 'Tech', 100.0, 105.0, 5.0, 1000000, 10.0)
negative = GapCandidate('B.NS', 'Bank', 100.0, 96.0, -4.0, 800000, 6.4)
candidates = [positive, negative]

# BULLISH: only positive gaps
bias_bull = MarketBias(bias='BULLISH', bias_strength=0.8, gift_nifty_gap_pct=0.5, valid_strategies=['GAP_AND_GO'], confidence=0.9)
result = apply_direction_filter(candidates, bias_bull)
assert len(result) == 1 and result[0].symbol == 'A.NS', f'BULLISH filter failed: {result}'

# BEARISH: treated as NEUTRAL, all pass
bias_bear = MarketBias(bias='BEARISH', bias_strength=0.7, gift_nifty_gap_pct=-0.3, valid_strategies=['GAP_FILL'], confidence=0.7)
result = apply_direction_filter(candidates, bias_bear)
assert len(result) == 2, f'BEARISH filter should return all: {result}'

# NEUTRAL: all pass
bias_neutral = MarketBias(bias='NEUTRAL', bias_strength=0.3, gift_nifty_gap_pct=0.0, valid_strategies=['GAP_AND_GO', 'ORB_BREAKOUT', 'GAP_FILL', 'VWAP_RECLAIM'], confidence=0.4)
result = apply_direction_filter(candidates, bias_neutral)
assert len(result) == 2, f'NEUTRAL filter should return all: {result}'

# gap_score formula check
c = GapCandidate('C.NS', 'FMCG', 100.0, 104.0, 4.0, 1_000_000, 0.0)
c.gap_score = abs(c.gap_pct) * min(c.prev_volume / 500_000, 3.0)
assert c.gap_score == 8.0, f'gap_score formula failed: {c.gap_score}'

print('agent_i1.py: all assertions passed')
"
```
