---
phase: 04B-market-session-agents
plan: 01
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 4b Plan 1 — Agent I6 Position Monitor

## Outcome
`agents/agent_i6.py` implemented.

## Key Details
- Stateful `AgentI6` checks open positions for exit signals, trailing SL updates, and circuit conditions.
- Trailing SL: trails at `current_price - 0.75 * ATR` once 1 ATR profit is reached for `GAP_AND_GO`. Moves to breakeven after partial exit for `ORB_BREAKOUT`.
- `GAP_FILL` and `VWAP_RECLAIM` use fixed SL.
- Circuit breaker: POSSIBLE_CIRCUIT is flagged if price remains unchanged for 3 consecutive polls.
- Partial exit: triggers at 1:1 R:R for `GAP_AND_GO` and `ORB_BREAKOUT`.
- Mutation calls are delegated to `PaperPortfolio`.
