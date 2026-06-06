---
wave: 1
plan_id: "04A-PLAN-A"
phase: "04A"
phase_name: "Pre-Market Agents"
objective: "Create agents/models.py shared dataclasses + agents/agent_i0.py global bias agent"
depends_on: []
files_modified:
  - agents/__init__.py
  - agents/models.py
  - agents/agent_i0.py
autonomous: true
requirements_addressed:
  - AGNT-01
  - AGNT-02
must_haves:
  truths:
    - "MarketBias is a Pydantic BaseModel with fields: bias, bias_strength, gift_nifty_gap_pct, valid_strategies, confidence"
    - "GapCandidate is a dataclass with fields: symbol, sector, prev_close, premarket_price, gap_pct, prev_volume, gap_score, catalyst_type='UNKNOWN', trade_recommendation='UNKNOWN'"
    - "WatchlistEntry is a dataclass with all price-level fields: symbol, sector, gap_pct, gap_score, strategy, entry_trigger, stop_loss, target, rr_ratio, catalyst_type, atr"
    - "AgentI0.run() returns MarketBias — never raises"
    - "When Gemini fails, rule-based fallback returns NEUTRAL bias with confidence=0.0"
    - "When Gemini returns confidence < 0.5, bias is overridden to NEUTRAL"
    - "AgentI0 uses google-genai SDK: from google import genai"
---

# Phase 4a Plan A: Shared Models + AgentI0 (Global Bias)

## Tasks

### Task 1: Create agents/__init__.py and agents/models.py

<read_first>
- .planning/phases/04A-pre-market-agents/04A-CONTEXT.md (D-01 through D-04 — Pydantic schemas and dataclass fields)
- .planning/phases/01-foundation/01-CONTEXT.md (import patterns)
- agents/ (check what exists — scaffold may have created __init__.py already)
</read_first>

<action>
Create `agents/__init__.py` as empty file if not present.

Create `agents/models.py` with all shared data structures:

**Pydantic models** (for Gemini structured output):
- `MarketBias(BaseModel)`: fields `bias: str`, `bias_strength: float`, `gift_nifty_gap_pct: float`, `valid_strategies: list[str]`, `confidence: float`
- `NewsAnalysis(BaseModel)`: fields `catalyst_type: str`, `trade_recommendation: str`, `summary: str`

**Dataclasses** (pipeline data transfer):
- `GapCandidate`: fields `symbol: str`, `sector: str`, `prev_close: float`, `premarket_price: float`, `gap_pct: float`, `prev_volume: int`, `gap_score: float`, `catalyst_type: str = "UNKNOWN"`, `trade_recommendation: str = "UNKNOWN"`
- `WatchlistEntry`: fields `symbol: str`, `sector: str`, `gap_pct: float`, `gap_score: float`, `strategy: str`, `entry_trigger: float`, `stop_loss: float`, `target: float`, `rr_ratio: float`, `catalyst_type: str`, `atr: float`

Imports needed: `from pydantic import BaseModel`, `from dataclasses import dataclass, field`
</action>

<acceptance_criteria>
- `agents/models.py` imports without error
- `from agents.models import MarketBias, NewsAnalysis, GapCandidate, WatchlistEntry` succeeds
- `MarketBias(bias="BULLISH", bias_strength=0.8, gift_nifty_gap_pct=0.5, valid_strategies=["GAP_AND_GO"], confidence=0.9)` instantiates without error
- `GapCandidate(symbol="RELIANCE.NS", sector="Energy", prev_close=2500.0, premarket_price=2600.0, gap_pct=4.0, prev_volume=1000000, gap_score=8.0)` instantiates with `catalyst_type="UNKNOWN"` default
- `WatchlistEntry` has `rr_ratio` and `atr` fields
- All four classes importable from single `agents/models.py` module
</acceptance_criteria>

---

### Task 2: Create agents/agent_i0.py — Gemini global bias agent

<read_first>
- .planning/phases/04A-pre-market-agents/04A-CONTEXT.md (D-01, D-01a through D-01e — Gemini schema, fallback, confidence override)
- CLAUDE.md §"3. google-generativeai / google-genai (Gemini Flash)" (import pattern, model name, GenerateContentConfig)
- .planning/STATE.md §"Key Decisions Made" — await asyncio.sleep not time.sleep
- agents/models.py (MarketBias schema)
- data/market_data.py (MarketDataFetcher.get_global_indices() return format)
- config.py (config.GEMINI_API_KEY)
</read_first>

<action>
Create `agents/agent_i0.py`:

**Module-level setup:**
- `from google import genai` and `from google.genai import types`
- `client = genai.Client(api_key=config.GEMINI_API_KEY)` at module level (created once, reused)
- `IST = pytz.timezone("Asia/Kolkata")`, `logger = setup_logger(__name__)`

**`async def run() -> MarketBias`** — main entry point:
1. Call `await asyncio.to_thread(_fetch_and_classify)` to run blocking I/O in thread pool
2. Return result

**`def _fetch_and_classify() -> MarketBias`** — sync inner function:
1. `indices_data = fetcher.get_global_indices()` — MarketDataFetcher instance (module-level or per-call)
2. If `indices_data` is None or empty → return `_rule_based_fallback({})`
3. Try `result = _call_gemini(indices_data)` — if any exception → return `_rule_based_fallback(indices_data)`
4. If `result.confidence < 0.5` → set `result.bias = "NEUTRAL"` (mutate in-place)
5. Return result

**`def _call_gemini(indices_data: dict) -> MarketBias`**:
- Build prompt string: list index names/values + ask for MarketBias JSON
- `response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=MarketBias))`
- `result = response.parsed` — if None → raise ValueError("response.parsed is None")
- Log INFO: `"🌐 Market bias: {result.bias} (strength={result.bias_strength:.2f}, confidence={result.confidence:.2f})"`
- Return result

**`def _rule_based_fallback(indices_data: dict) -> MarketBias`**:
- Simple rule: if `"^GSPC"` in indices_data and `indices_data["^GSPC"]["change_pct"] > 0.5` → bias="BULLISH"
- If `"^GSPC"` in indices_data and `indices_data["^GSPC"]["change_pct"] < -0.5` → bias="BEARISH"
- Otherwise → bias="NEUTRAL"
- Always: `confidence=0.0`, `bias_strength=0.3`, `valid_strategies=["GAP_AND_GO", "ORB_BREAKOUT", "GAP_FILL", "VWAP_RECLAIM"]`, `gift_nifty_gap_pct=0.0`
- Log WARNING: `"⚠ AgentI0 using rule-based fallback (Gemini unavailable)"`
</action>

<acceptance_criteria>
- `agents/agent_i0.py` imports without error
- `from agents.agent_i0 import run` succeeds
- `run()` is a coroutine (`asyncio.iscoroutinefunction(run)` returns True)
- Gemini import uses `from google import genai` — NOT `import google.generativeai`
- `google-generativeai` package NOT imported anywhere in file
- `client` is module-level (not recreated per call)
- `_rule_based_fallback({})` returns `MarketBias` with `bias="NEUTRAL"`, `confidence=0.0`
- `_rule_based_fallback({"^GSPC": {"change_pct": 1.2}})` returns `MarketBias` with `bias="BULLISH"`
- If `_call_gemini` raises any exception, `run()` catches and returns rule-based fallback (never raises)
- MarketBias with confidence=0.3 after Gemini call → bias remains as Gemini returned it (only < 0.5 triggers NEUTRAL override)
- MarketBias with confidence=0.4 → bias overridden to "NEUTRAL"
- Log line contains "🌐 Market bias:" on successful Gemini call
- Log line contains "⚠ AgentI0 using rule-based fallback" on failure
</acceptance_criteria>

---

## Verification

```bash
python -c "
from agents.models import MarketBias, NewsAnalysis, GapCandidate, WatchlistEntry

# Pydantic models
mb = MarketBias(bias='NEUTRAL', bias_strength=0.5, gift_nifty_gap_pct=0.2, valid_strategies=['GAP_AND_GO'], confidence=0.0)
assert mb.bias == 'NEUTRAL'
assert mb.confidence == 0.0

na = NewsAnalysis(catalyst_type='UNKNOWN', trade_recommendation='UNKNOWN', summary='test')
assert na.catalyst_type == 'UNKNOWN'

# Dataclasses
gc = GapCandidate('RELIANCE.NS', 'Energy', 2500.0, 2600.0, 4.0, 1000000, 8.0)
assert gc.catalyst_type == 'UNKNOWN'

we = WatchlistEntry('RELIANCE.NS', 'Energy', 4.0, 8.0, 'GAP_AND_GO', 2605.2, 2530.0, 2662.5, 1.6, 'EARNINGS', 50.0)
assert we.rr_ratio == 1.6

print('models.py: all assertions passed')
"

python -c "
import asyncio
from agents.agent_i0 import _rule_based_fallback, run
from agents.models import MarketBias

# Test fallback directly
r1 = _rule_based_fallback({})
assert r1.bias == 'NEUTRAL', f'Expected NEUTRAL, got {r1.bias}'
assert r1.confidence == 0.0

r2 = _rule_based_fallback({'^GSPC': {'change_pct': 1.5}})
assert r2.bias == 'BULLISH', f'Expected BULLISH, got {r2.bias}'

r3 = _rule_based_fallback({'^GSPC': {'change_pct': -1.5}})
assert r3.bias == 'BEARISH', f'Expected BEARISH, got {r3.bias}'

# run() is async and returns MarketBias
result = asyncio.run(run())
assert isinstance(result, MarketBias), f'Expected MarketBias, got {type(result)}'
assert result.bias in ('BULLISH', 'BEARISH', 'NEUTRAL'), f'Invalid bias: {result.bias}'
print(f'AgentI0 result: {result.bias} confidence={result.confidence:.2f}')
print('agent_i0.py: all assertions passed')
"
```
