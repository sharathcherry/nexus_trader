---
phase: 04a-pre-market-agents
plan: 04A-PLAN-B
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 4a Plan B — Agent I1 Gap Scanner

## Outcome
`agents/agent_i1.py` implemented.

## Key Details
- Coroutine `AgentI1.run()` scans the hardcoded 100-stock universe and filters candidates based on gap criteria.
- Filters: `abs(gap_pct)` between 1.5% and 8.0%, `prev_volume` >= 500,000, and price between 50 and 5,000.
- `gap_score` computed as `abs(gap_pct) * min(prev_volume / 500_000, 3.0)`.
- Excludes stocks on their ex-dividend, bonus, or split dates.
- Limits outputs to top 20 candidates sorted by `gap_score` descending.
- Rule-based fallback returns an empty watchlist (NO_TRADE_DAY signal) if fewer than 3 candidates are found.
