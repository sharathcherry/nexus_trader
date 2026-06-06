# Phase 4c: Post-Market Agent - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

AgentI9 runs once after each trading session at 15:35 IST. It fetches today's trade ledger and 20-day rolling stats from SQLite, calls Claude Sonnet via streaming, parses the structured review response, validates parameter suggestions, and saves the result to `logs/performance/`. No scheduling — Phase 5 orchestrator triggers it. Delivers `agents/agent_i9.py`.

</domain>

<decisions>
## Implementation Decisions

### Claude Sonnet call pattern
- **D-01:** Stream text, parse JSON at end. Use `client.messages.stream()` (Anthropic streaming API), accumulate all text chunks into `full_text`, then `json.loads(full_text)` + Pydantic validation after stream completes. This satisfies AGNT-13's streaming requirement (partial response captured) while supporting structured output.
- **D-02:** Model: `claude-sonnet-4-6` (from CLAUDE.md §"4. anthropic SDK" > "Model Name"). Prompt capped at 10,000 tokens — measure before calling. Log token count estimate at INFO before each call.
- **D-03:** System prompt instructs Claude to respond with a single JSON object matching the `DailyReview` schema. No tool_use, no function calling — plain JSON in assistant turn.

### Partial response handling
- **D-04:** Three output states depending on what stream produces:
  1. **Full valid response**: stream completes → JSON parses → Pydantic validates → write `review_YYYYMMDD.json`
  2. **Stream completes but JSON invalid/truncated**: write raw accumulated text to `review_partial_YYYYMMDD.json` AND write `review_failed_YYYYMMDD.json` (sentinel with `{"error": "json_parse_failed", "date": ...}`)
  3. **Stream raises exception**: write `review_failed_YYYYMMDD.json` only (no text to save)
- **D-05:** Tabulate terminal summary prints in ALL three states. If review failed: print "Review generation failed — check review_failed_YYYYMMDD.json" with today's date. If partial: print "Partial review — raw text saved" plus whatever fields could be extracted.

### Pydantic response schema
- **D-06:** `DailyReview` Pydantic model:
  ```python
  class ParameterChange(BaseModel):
      param_name: str        # "MAX_OPEN_POSITIONS" / "RISK_PER_TRADE_PCT" / etc.
      current_value: float
      suggested_value: float
      reason: str

  class DailyReview(BaseModel):
      session_verdict: str               # "PROFITABLE" / "BREAKEVEN" / "LOSS"
      winning_strategies: list[str]      # strategy names that outperformed
      underperforming_strategies: list[str]
      parameter_adjustments: list[ParameterChange]
      tomorrow_watch: list[str]          # up to 5 symbols
      summary: str                       # free-text executive summary
  ```

### Parameter advisory validation (AGNT-15)
- **D-07:** After Pydantic parse, iterate `parameter_adjustments` list. Auto-reject (remove from list + log WARNING) any `ParameterChange` where:
  - `param_name == "MAX_OPEN_POSITIONS"` AND `suggested_value > config.MAX_OPEN_POSITIONS` (raises limit)
  - `param_name == "MIN_RISK_REWARD"` AND `suggested_value < 1.5` (weakens R:R floor)
  - `param_name == "RISK_PER_TRADE_PCT"` AND `suggested_value > 1.5` (increases risk)
  - Remaining (valid) suggestions preserved in the saved JSON
- **D-08:** `tomorrow_watch` is `list[str]` of symbol names only (e.g. `["RELIANCE.NS", "TCS.NS"]`). No sector tags. No extra validation — AGNT-15's 3 rules are exhaustive.

### 20-day rolling stats content
- **D-09:** Rolling stats block = strategy-level breakdown for last 20 trading days. Per strategy: `trade_count`, `win_rate`, `avg_net_pnl`, `avg_rr_achieved`. Plus overall totals: `total_trades`, `total_net_pnl`, `win_rate_overall`. Computed from `trades` table `WHERE DATE(exit_time) >= today - 20 days`.
- **D-10:** Token cap truncation order: if prompt exceeds 10,000 tokens, drop oldest days from rolling stats first (keep today's full ledger intact). If still over after dropping to 10-day window, truncate individual trade records by dropping `entry_time`/`exit_time` fields. Log truncation at WARNING with how many days were dropped.

### Output files and structure
- **D-11:** All output files in `logs/performance/` directory (created on first run if absent).
  - Success: `review_YYYYMMDD.json` — full `DailyReview` JSON including validated `parameter_adjustments`
  - Partial stream: `review_partial_YYYYMMDD.json` (raw accumulated text) + `review_failed_YYYYMMDD.json` (sentinel)
  - Full failure: `review_failed_YYYYMMDD.json` only, with `{"error": "<reason>", "date": "YYYYMMDD"}`

### Claude's Discretion
- Exact system prompt wording (tone: analytical, concise, NSE-specific)
- Whether to include VWAP/ATR values in the per-trade ledger sent to Claude
- Exact tabulate table columns for terminal summary (suggested: symbol, strategy, entry, exit, net_pnl, exit_reason)
- Whether `session_verdict` is inferred by AgentI9 from `net_pnl` or trusted from Claude's response

</decisions>

<specifics>
## Specific Ideas

- **Streaming pattern**: `with client.messages.stream(...) as stream: for text in stream.text_stream: full_text += text`. After context manager exits, `full_text` contains the complete response even if partially received (the `with` block guarantees cleanup).
- **Token estimation**: use `len(prompt_text) // 4` as rough token estimate before the call (no tokenizer required — this is a conservative 4 chars/token heuristic sufficient for cap checking).
- **20-day query**: `SELECT strategy, COUNT(*) as trade_count, AVG(net_pnl) as avg_net_pnl, SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate FROM trades WHERE DATE(exit_time) >= DATE('now', '-20 days') GROUP BY strategy`
- **Data source**: `portfolio.get_daily_report()` returns today's closed trades. Rolling stats computed directly from SQLite `trades` table by AgentI9 (not via PaperPortfolio method — that method only covers today).

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Agent requirements
- `.planning/REQUIREMENTS.md` §"Agents" (AGNT-13 through AGNT-16) — complete requirement set for this phase

### Anthropic SDK patterns
- `CLAUDE.md` §"4. anthropic SDK (Claude Sonnet)" — streaming pattern, structured output, model name `claude-sonnet-4-6`
- `CLAUDE.md` §"4. anthropic SDK" > "Structured JSON Output Patterns" — note: AgentI9 uses streaming not structured output; parse JSON manually from streamed text

### Prior phase data sources
- `.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md` — D-01 (trades table schema: symbol, entry_price, exit_price, qty, strategy, entry_time, exit_time, gross_pnl, brokerage, net_pnl, exit_reason), `get_daily_report()` returns today's trades
- `.planning/phases/04B-market-session-agents/04B-CONTEXT.md` — AgentI4 is caller that triggers AgentI9 indirectly via Phase 5; AgentI9 reads portfolio state AFTER AgentI4 exits

### Phase goal
- `.planning/ROADMAP.md` §"Phase 4c: Post-Market Agent" — 4 success criteria define done

### Project constraints
- `.planning/STATE.md` §"Key Decisions Made" — 15-minute yfinance data delay must be noted in Claude prompt ("data is 15-min delayed")

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (exist after Phases 1–4b)
- `execution/portfolio.py` → `PaperPortfolio.get_daily_report()` — today's closed trades
- `execution/portfolio.db` → `trades` table — source for 20-day rolling stats query
- `config.py` → `config.ANTHROPIC_API_KEY`, `config.MAX_OPEN_POSITIONS` (5), `config.MIN_RR_RATIO` (1.5), `config.RISK_PER_TRADE_PCT` (1.0)
- `utils/logger.py` → `setup_logger(__name__)`

### Established Patterns
- Error contract: methods return None/empty on failure, never raise to caller
- `from config import config` at module level
- `logs/` directory structure from SCAF-01

### Integration Points
- AgentI9 receives `PaperPortfolio` instance from Phase 5 orchestrator
- `portfolio.get_daily_report()` → AgentI9 prompt construction
- `execution/portfolio.db` → direct SQLite query for 20-day rolling stats
- AgentI9 output (review JSON) → human reads post-session; no downstream agent consumes it

</code_context>

<deferred>
## Deferred Ideas

- Telegram notification with review summary (ALRT-01/v2 scope)
- Auto-apply validated parameter suggestions to config (explicitly out-of-scope in REQUIREMENTS.md)
- Multi-day trend analysis (Sharpe, max drawdown) in the Claude prompt — deferred to v2

</deferred>

---

*Phase: 04C-post-market-agent*
*Context gathered: 2026-06-06*
