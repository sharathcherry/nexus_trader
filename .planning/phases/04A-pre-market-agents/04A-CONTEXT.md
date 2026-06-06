# Phase 4a: Pre-Market Agents - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Four pre-market agents (I0→I1→I2→I3) that run 8:30–9:10 AM IST and produce a ranked watchlist before market open. No live trading logic, no intraday data, no APScheduler — that is Phase 5. Delivers `agents/agent_i0.py`, `agents/agent_i1.py`, `agents/agent_i2.py`, `agents/agent_i3.py`.

**Pipeline flow:**
```
I0 (global bias)   ──┐
                      ├── asyncio.gather → I2 (news) → I3 (watchlist)
I1 (gap scanner)   ──┘
```

I0 + I1 run concurrently via `asyncio.gather`. I2 runs after I1 (needs I1 candidates). I3 runs after I2 (needs sentiment filter).

</domain>

<decisions>
## Implementation Decisions

### Gemini structured output
- **D-01:** Pydantic models define output schema for both AgentI0 and AgentI2. Schema passed as `response_schema=<PydanticClass>` in `types.GenerateContentConfig`. On any failure (API error, `response.parsed is None`, validation error) → catch exception, log WARNING, return rule-based/UNKNOWN fallback. Never raise to caller.
- **D-01a:** Gemini client pattern:
  ```python
  from google import genai
  from google.genai import types
  
  client = genai.Client(api_key=config.GEMINI_API_KEY)
  response = client.models.generate_content(
      model="gemini-2.0-flash",
      contents=prompt,
      config=types.GenerateContentConfig(
          response_mime_type="application/json",
          response_schema=MarketBias,
      ),
  )
  result = response.parsed   # validated Pydantic instance or None
  ```
- **D-01b:** AgentI0 Pydantic schema:
  ```python
  class MarketBias(BaseModel):
      bias: str           # "BULLISH" / "BEARISH" / "NEUTRAL"
      bias_strength: float  # 0.0–1.0
      gift_nifty_gap_pct: float
      valid_strategies: list[str]
      confidence: float   # 0.0–1.0
  ```
- **D-01c:** AgentI2 Pydantic schema per stock:
  ```python
  class NewsAnalysis(BaseModel):
      catalyst_type: str        # "EARNINGS" / "BROKER_UPGRADE" / "BLOCK_DEAL" / "INDEX_REBALANCE" / "MACRO" / "UNKNOWN"
      trade_recommendation: str # "TRADE" / "AVOID" / "UNKNOWN"
      summary: str
  ```
- **D-01d:** Fallback rules: AgentI0 → NEUTRAL bias, all strategies valid, confidence=0.0. AgentI2 → UNKNOWN catalyst, UNKNOWN recommendation.
- **D-01e:** If AgentI0 returns `confidence < 0.5` (even from Gemini) → override bias to NEUTRAL.

### Gap score formula
- **D-02:** `gap_score = abs(gap_pct) * min(prev_volume / 500_000, 3.0)`
  - Volume multiplier capped at 3.0 — prevents 10× volume from dominating completely.
  - Uses `abs(gap_pct)` so both gap-up and gap-down score equally.
  - AgentI1 ranks top 20 candidates by `gap_score` descending.
- **D-03:** NEUTRAL bias allows both positive and negative gap candidates. BULLISH bias keeps only positive gap_pct. BEARISH bias is treated as NEUTRAL in v1 (long-only system — no short selling).
- **D-04:** Candidate dataclass from AgentI1:
  ```python
  @dataclass
  class GapCandidate:
      symbol: str
      sector: str
      prev_close: float
      premarket_price: float
      gap_pct: float
      prev_volume: int
      gap_score: float
  ```

### AgentI2 batching
- **D-05:** One Gemini API call per stock. No batch endpoint — Gemini Flash processes one symbol per call.
- **D-06:** `asyncio.sleep(1)` between each call (1 second delay). Not `time.sleep()` — I2 runs in async context.
- **D-07:** Up to 5 yfinance news headlines per symbol (`ticker.news[:5]`). If `ticker.news` is empty → skip Gemini call, return `NewsAnalysis(catalyst_type="UNKNOWN", trade_recommendation="UNKNOWN", summary="No news found")`.
- **D-08:** Filter out `BLOCK_DEAL` and `INDEX_REBALANCE` catalysts (AGNT-06). Filter out `AVOID` recommendations. Both filters applied after I2 returns, before I3 receives candidates.

### AgentI3 strategy assignment and price levels
- **D-09:** Strategy selection is deterministic rule table (no AI call). Rules in priority order:
  1. `GAP_AND_GO`: `abs(gap_pct) > 3.0` AND `bias == "BULLISH"`
  2. `ORB_BREAKOUT`: `abs(gap_pct) > 2.0` AND `bias == "NEUTRAL"`
  3. `GAP_FILL`: `1.5 <= abs(gap_pct) <= 3.0` (any bias — mean reversion play)
  4. `VWAP_RECLAIM`: `abs(gap_pct) < 2.0` (any bias)
  - If no rule matches (shouldn't happen with 1.5–8% filter): assign `VWAP_RECLAIM`.
- **D-10:** AgentI3 fetches ATR for each candidate via `MarketDataFetcher.get_atr(symbol)`. 14-period daily ATR. If ATR fetch fails → skip symbol (cannot compute levels without ATR).
- **D-11:** Price level formulas (all using `premarket_price` + `atr`):

  | Strategy | entry_trigger | stop_loss | target |
  |----------|--------------|-----------|--------|
  | GAP_AND_GO | `premarket * 1.002` | `entry - 1.5 * atr` | `entry + 2.25 * atr` |
  | GAP_FILL | `premarket * 0.998` | `entry - 1.0 * atr` | `prev_close` |
  | ORB_BREAKOUT | `premarket * 1.005` (I4 overrides with actual ORB high at 09:30) | `premarket * (1 - abs(gap_pct)/100) - 0.5 * atr` | `entry + 2.0 * atr` |
  | VWAP_RECLAIM | `premarket * 1.001` | `entry - 1.0 * atr` | `entry + 1.5 * atr` |

- **D-12:** R:R filter: `rr_ratio = (target - entry_trigger) / (entry_trigger - stop_loss)`. If `rr_ratio < config.MIN_RR_RATIO` (1.5) → skip symbol (AGNT-08). GAP_AND_GO (2.25/1.5 = 1.5) and VWAP_RECLAIM (1.5/1.0 = 1.5) always pass by construction. GAP_FILL may fail if prev_close gap is too small.
- **D-13:** AgentI3 returns top 10 watchlist entries sorted by `gap_score` descending after all filters. Watchlist dataclass:
  ```python
  @dataclass
  class WatchlistEntry:
      symbol: str
      sector: str
      gap_pct: float
      gap_score: float
      strategy: str
      entry_trigger: float
      stop_loss: float
      target: float
      rr_ratio: float
      catalyst_type: str
      atr: float
  ```

### Phase synchronization
- **D-14:** `watchlist_ready` is an `asyncio.Event` object passed into the pre-market pipeline (created in Phase 5 orchestrator). AgentI3 calls `watchlist_ready.set()` after returning the watchlist. Phase 5 market session waits on `watchlist_ready.wait()` before starting AgentI4.

### Claude's Discretion
- Exact Gemini prompt wording for I0 (global macro → bias classification) and I2 (headlines → catalyst)
- Whether `client = genai.Client()` is module-level or per-call (module-level preferred)
- yfinance news format — `ticker.news` returns list of dicts; headline key is `"title"` in current API
- AgentI1 NO_TRADE_DAY detection: if < 3 gap candidates found after all filters → return empty list, signal to orchestrator

</decisions>

<specifics>
## Specific Ideas

- **Gemini TPM budget**: Gemini free tier reduced TPM December 2025 (from STATE.md critical pitfall #8). Log token usage from first I0 call. If 429 received → fall back immediately to rule-based, do not retry.
- **Corporate action filter**: AGNT-03 says I1 must filter ex-dividend/bonus/split dates. Source: `nselib` bhav copy or yfinance `ticker.calendar`. If unavailable, skip the filter rather than block the pipeline.
- **ORB entry_trigger placeholder**: AgentI3 sets a placeholder entry_trigger for ORB_BREAKOUT using `premarket * 1.005`. AgentI4 (Phase 4b) overrides this with the actual ORB high at 09:30 when the first 15-minute candle closes. Both agents must store the entry_trigger in the same WatchlistEntry object passed through.
- **Async I0+I1**: Both agents are `async def run()` methods. `results = await asyncio.gather(i0.run(), i1.run())`. If I1 returns empty list → pipeline aborts (no candidates to process with I2/I3).
- **Price filter at I1**: gap_pct filter is abs(gap_pct) 1.5%–8.0%, prev_volume ≥ 500k, price ₹50–₹5000 (from AGNT-03). Price checked against `premarket_price`.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Agent requirements
- `.planning/REQUIREMENTS.md` §"Agents" (AGNT-01 through AGNT-08) — complete requirement set for this phase

### SDK patterns
- `CLAUDE.md` §"3. google-generativeai / google-genai (Gemini Flash)" — correct import `from google import genai`, Pydantic schema pattern, model names
- `CLAUDE.md` §"3. google-generativeai / google-genai" > "Correct Pattern for JSON Structured Output" — `response_mime_type + response_schema` pattern

### Phase context (prior decisions)
- `.planning/STATE.md` §"Key Decisions Made" — `asyncio.gather` for I0+I1, `watchlist_ready` Event, `await asyncio.sleep` not `time.sleep`
- `.planning/phases/02-data-layer/02-CONTEXT.md` (D-11) — `MarketDataFetcher.get_atr()` fetches internally; `Indicators.atr(df)` uses caller DataFrame
- `.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md` (D-10) — `OrderManager.calculate_quantity()` is called by AgentI4 (Phase 4b), not AgentI3

### Phase goal
- `.planning/ROADMAP.md` §"Phase 4a: Pre-Market Agents" — success criteria (watchlist printed to terminal before 09:15, no crashes on Gemini failure)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (exist after Phase 2)
- `data/market_data.py` — `MarketDataFetcher.get_premarket_price()`, `.get_previous_close()`, `.get_atr()`, `.get_global_indices()`
- `data/universe.py` — 100-stock universe as list of dicts `[{"symbol": "...", "sector": "..."}]`
- `config.py` — `config.GEMINI_API_KEY`, `config.MIN_PRICE`, `config.MAX_PRICE`, `config.MIN_GAP_PCT` (1.5), `config.MAX_GAP_PCT` (8.0), `config.MIN_VOLUME`, `config.MIN_RR_RATIO` (1.5), `config.MAX_WATCHLIST_SIZE` (10), `config.MAX_GAP_CANDIDATES` (20)
- `utils/logger.py` — `setup_logger(__name__)`

### Integration Points
- `WatchlistEntry` list returned by AgentI3 → AgentI4 signal engine (Phase 4b)
- `watchlist_ready` asyncio.Event → Phase 5 orchestrator (gates market session start)
- `PaperPortfolio` NOT used in Phase 4a — only AgentI4+ accesses it

</code_context>

<deferred>
## Deferred Ideas

- Telegram watchlist notification at 09:10 (ALRT-02 / v2 scope)
- Sector rotation scoring (favor sectors with strong global correlations)
- Multiple gap candidates per stock from different time windows

</deferred>

---

*Phase: 04A-pre-market-agents*
*Context gathered: 2026-06-06*
