---
wave: 3
plan_id: "04A-PLAN-C"
phase: "04A"
phase_name: "Pre-Market Agents"
objective: "Create agents/agent_i2.py — news catalyst agent: Gemini per-stock sentiment, BLOCK_DEAL/INDEX_REBALANCE filter"
depends_on:
  - "04A-PLAN-B"
files_modified:
  - agents/agent_i2.py
autonomous: true
requirements_addressed:
  - AGNT-05
  - AGNT-06
must_haves:
  truths:
    - "AgentI2 makes one Gemini call per candidate with 1s asyncio.sleep between calls"
    - "If ticker.news is empty, returns NewsAnalysis with catalyst_type='UNKNOWN' (no Gemini call)"
    - "Candidates with catalyst_type BLOCK_DEAL or INDEX_REBALANCE are removed from output"
    - "Candidates with trade_recommendation AVOID are removed from output"
    - "AgentI2.run() is a coroutine, never raises"
    - "Gemini failure for a single stock returns UNKNOWN — does not abort the loop"
    - "Up to 5 headlines from ticker.news[:5] are passed to Gemini"
---

# Phase 4a Plan C: AgentI2 (News Catalyst)

## Tasks

### Task 1: Create agents/agent_i2.py — Gemini news classification per candidate

<read_first>
- .planning/phases/04A-pre-market-agents/04A-CONTEXT.md (D-01 through D-01e — NewsAnalysis schema, fallback; D-05 through D-08 — batching, 1s delay, news format)
- CLAUDE.md §"3. google-generativeai / google-genai (Gemini Flash)" (GenerateContentConfig pattern)
- agents/models.py (NewsAnalysis Pydantic model, GapCandidate dataclass)
- config.py (config.GEMINI_API_KEY)
</read_first>

<action>
Create `agents/agent_i2.py`:

**Module-level:**
- `from google import genai` and `from google.genai import types`
- `client = genai.Client(api_key=config.GEMINI_API_KEY)` at module level
- `logger = setup_logger(__name__)`
- `_FILTER_CATALYSTS = {"BLOCK_DEAL", "INDEX_REBALANCE"}`

**`async def run(candidates: list[GapCandidate]) -> list[GapCandidate]`** — main entry point:
1. Iterate candidates with index, log start: `"📰 AgentI2 processing {len(candidates)} candidates"`
2. For each candidate:
   a. `await asyncio.sleep(1)` — 1s delay before each Gemini call (not after last one)
   b. Call `_classify_news(candidate)` — sync, runs in current thread (no heavy I/O; yfinance news is quick)
   c. Populate `candidate.catalyst_type` and `candidate.trade_recommendation` with result
3. Apply filters (post-loop):
   - Remove if `candidate.catalyst_type in _FILTER_CATALYSTS`
   - Remove if `candidate.trade_recommendation == "AVOID"`
4. Log INFO: `"📰 AgentI2: {len(filtered)}/{len(candidates)} candidates passed news filter"`
5. Return filtered list

**`def _classify_news(candidate: GapCandidate) -> NewsAnalysis`** — sync:
1. Fetch news: `ticker = yf.Ticker(candidate.symbol)` → `news_items = ticker.news or []`
2. If `len(news_items) == 0` → log DEBUG f"{candidate.symbol}: no news" → return `NewsAnalysis(catalyst_type="UNKNOWN", trade_recommendation="UNKNOWN", summary="No news found")`
3. Extract headlines: `headlines = [item.get("title", "") for item in news_items[:5] if item.get("title")]`
4. Build prompt:
   ```
   Analyze these news headlines for {symbol} (Indian stock, NSE listed):
   {chr(10).join(f"- {h}" for h in headlines)}
   
   Classify the catalyst type and trading recommendation.
   catalyst_type: one of EARNINGS, BROKER_UPGRADE, BROKER_DOWNGRADE, BLOCK_DEAL, INDEX_REBALANCE, MACRO, CORPORATE_ACTION, UNKNOWN
   trade_recommendation: one of TRADE, AVOID, UNKNOWN
   summary: brief 1-sentence summary of the catalyst
   ```
5. `response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=NewsAnalysis))`
6. `result = response.parsed` — if None → raise ValueError
7. Return result
8. Wrap steps 3-7 in try/except — on any exception: log WARNING f"{symbol}: Gemini classification failed ({e})" → return `NewsAnalysis(catalyst_type="UNKNOWN", trade_recommendation="UNKNOWN", summary="Classification failed")`
</action>

<acceptance_criteria>
- `agents/agent_i2.py` imports without error
- `run()` is a coroutine
- Module-level `client = genai.Client(...)` present — NOT recreated per call
- `from google import genai` used — NOT `import google.generativeai`
- `asyncio.sleep(1)` called before each Gemini call (not `time.sleep`)
- Empty `ticker.news` → returns NewsAnalysis with `catalyst_type="UNKNOWN"`, no Gemini call made
- `_FILTER_CATALYSTS = {"BLOCK_DEAL", "INDEX_REBALANCE"}` defined
- Candidate with `catalyst_type="BLOCK_DEAL"` is NOT in returned list
- Candidate with `trade_recommendation="AVOID"` is NOT in returned list
- Gemini failure on one stock does not abort loop — that stock gets UNKNOWN and remains (then passes filter since UNKNOWN != AVOID)
- `catalyst_type` and `trade_recommendation` written back to candidate objects in-place before filtering
- `run([])` returns `[]` immediately (empty input)
</acceptance_criteria>

---

## Verification

```bash
python -c "
import asyncio
from agents.agent_i2 import run, _classify_news
from agents.models import GapCandidate, NewsAnalysis

# Test filter logic by creating mock candidates with pre-set catalyst types
c1 = GapCandidate('A.NS', 'Tech', 100.0, 105.0, 5.0, 1000000, 10.0)
c1.catalyst_type = 'EARNINGS'
c1.trade_recommendation = 'TRADE'

c2 = GapCandidate('B.NS', 'Bank', 100.0, 106.0, 6.0, 800000, 9.6)
c2.catalyst_type = 'BLOCK_DEAL'
c2.trade_recommendation = 'AVOID'

c3 = GapCandidate('C.NS', 'FMCG', 100.0, 104.0, 4.0, 700000, 4.2)
c3.catalyst_type = 'INDEX_REBALANCE'
c3.trade_recommendation = 'AVOID'

c4 = GapCandidate('D.NS', 'IT', 100.0, 103.0, 3.0, 600000, 3.6)
c4.catalyst_type = 'UNKNOWN'
c4.trade_recommendation = 'TRADE'

# Test filter directly without Gemini (test filter logic only)
from agents.agent_i2 import _FILTER_CATALYSTS
candidates = [c1, c2, c3, c4]
filtered = [c for c in candidates if c.catalyst_type not in _FILTER_CATALYSTS and c.trade_recommendation != 'AVOID']
assert len(filtered) == 2, f'Expected 2 after filter, got {len(filtered)}'
assert filtered[0].symbol == 'A.NS'
assert filtered[1].symbol == 'D.NS'

# run([]) returns empty
result = asyncio.run(run([]))
assert result == [], f'Empty input should return []: {result}'

print('agent_i2.py: all assertions passed')
"
```
