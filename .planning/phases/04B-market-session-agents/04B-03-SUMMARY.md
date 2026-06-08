---
phase: 04B-market-session-agents
plan: 03
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 4b Plan 3 — Agent I4 Signal Evaluation

## Outcome
`agents/agent_i4.py` execution loop and strategy evaluators implemented.

## Key Details
- Coroutine `AgentI4.run()` waits on `watchlist_ready` event and runs 60-second polling loop.
- Polling loop uses `await asyncio.sleep(60)` to prevent blocking the event loop.
- Entry signals evaluated for all four strategies (GAP_AND_GO, ORB_BREAKOUT, GAP_FILL, VWAP_RECLAIM).
- Entry time gate enforced: no buys before 09:30 IST or after 14:00 IST.
- Single-instance order entry guard: ignores candidates already in portfolio or marked as circuit.
- Market session cleanly shut down at 15:15 IST by calling `force_squareoff_all()`.
