# Phase 4c: Post-Market Agent - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-06-06
**Phase:** 04C-post-market-agent
**Mode:** discuss
**Areas discussed:** Streaming + structured output pattern, 20-day rolling stats content, Parameter advisory Pydantic schema, Partial response handling on failure

---

## Area 1: Streaming + structured output pattern

**Question:** How should AgentI9 call Claude Sonnet — streaming with manual JSON parse, non-streaming structured output, or streaming with tool_use?

**Options presented:**
- Stream text, parse JSON at end ← **Selected**
- Non-streaming with extended timeout
- Streaming with tool_use to force JSON

**Decision:** `client.messages.stream()` to accumulate full_text, then json.loads + Pydantic at end.

**Follow-up:** When streaming accumulates text but JSON parse fails, what gets saved?
- Save raw text to review_partial_YYYYMMDD.json ← **Selected**
- Discard partial, write sentinel only

**Decision:** Three-state output: full review JSON on success, partial text + sentinel on parse failure, sentinel only on exception.

---

## Area 2: 20-day rolling stats content

**Question:** What fields go into the 20-day rolling stats block?

**Options presented:**
- Strategy-level breakdown ← **Selected**
- Session-level daily summaries
- Minimal totals only

**Decision:** Per-strategy: trade_count, win_rate, avg_net_pnl, avg_rr_achieved. Plus overall totals.

**Follow-up:** Truncation order when prompt exceeds 10,000 token cap?
- Truncate oldest rolling stats rows first ← **Selected**
- Truncate individual trade details
- Hard cap at character count

**Decision:** Drop oldest days from rolling stats first (keep today's full ledger). Log truncation at WARNING.

---

## Area 3: Parameter advisory Pydantic schema

**Question:** Shape of parameter_adjustments field?

**Options presented:**
- List of ParameterChange objects ← **Selected**
- Free-text advisory string
- Dict[str, float]

**Decision:** `List[ParameterChange]` with param_name, current_value, suggested_value, reason. AGNT-15 validation iterates this list.

**Follow-up:** What should tomorrow_watch contain + any extra validation rules?
- List[str] of symbols + no extra validation rules ← **Selected**
- List[WatchSymbol] + sector tags + extra rules

**Decision:** `list[str]` symbol names only. AGNT-15's 3 rejection rules are exhaustive.

---

## Area 4: Partial response handling on failure

*Covered in Area 1 follow-up discussion above.*

---

## Claude's Discretion Items

- Exact system prompt wording
- Whether to include VWAP/ATR values in per-trade ledger sent to Claude
- Tabulate table columns for terminal summary
- Whether session_verdict is inferred from net_pnl or trusted from Claude's response

---

## Deferred Ideas

- Telegram notification with review summary (v2 ALRT-01 scope)
- Auto-apply validated parameters (explicitly out-of-scope per REQUIREMENTS.md)
- Sharpe/max drawdown in Claude prompt (v2)
