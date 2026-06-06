---
phase: "03"
plan: "03-PLAN-B"
subsystem: "execution"
tags: [order-manager, quantity-sizing, trailing-stop, exit-logic]
dependency_graph:
  requires: [PaperPortfolio, config.CAPITAL, config.RISK_PER_TRADE_PCT]
  provides: [OrderManager]
  affects: [agents/I4, agents/I3, main.py, Phase5-orchestrator]
tech_stack:
  added: []
  patterns: [quantity sizing by risk, trailing stop logic, idempotent exit gate, circuit breaker detection]
key_files:
  created: [execution/order_manager.py]
  modified: []
decisions:
  - "calculate_quantity caps at 10% of config.CAPITAL (not current portfolio capital) — deterministic sizing across restarts"
  - "check_and_execute_exits: target check runs before partial exit — same price (1:1 R:R = target in many cases) means target fires and continue prevents double-execution"
  - "15:15 gate uses datetime.now(IST) directly — dual safety with APScheduler date job (Phase 5)"
  - "_price_history dict tracks last 3 prices in-memory — circuit breaker resets on restart (acceptable for intraday)"
metrics:
  duration_minutes: 12
  completed: "2026-06-06"
  tasks_completed: 3
  files_created: 1
---

# Phase 3 Plan B: OrderManager Summary

**One-liner:** Stateless order execution layer over PaperPortfolio: 1%-risk quantity sizing capped at 10% capital, 15:15 force-squareoff gate, target/SL/partial exit per polling cycle, and strategy-specific trailing stops (GAP_AND_GO at 0.75 ATR, ORB_BREAKOUT at breakeven).

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| B-1 | create order_manager.py skeleton + calculate_quantity() | 317f559 |
| B-2 | check_and_execute_exits() with target/SL/partial exit + circuit breaker | 317f559 |
| B-3 | update_trailing_stops() for GAP_AND_GO (0.75 ATR) and ORB_BREAKOUT (breakeven) | 317f559 |

## Verification Results

- calculate_quantity(500, 490) = 20 (risk=Rs1000, risk/share=Rs10, raw=100, capped at 10% capital)
- calculate_quantity(500, 500) = 0 (zero risk_per_share)
- Target hit closes position with exit_reason="TARGET"
- Stop loss hit closes position with exit_reason="STOP_LOSS"
- 15:15 IST gate triggers force_squareoff_all() and returns
- Circuit breaker: POSSIBLE_CIRCUIT WARNING after 3 consecutive identical prices
- GAP_AND_GO: SL trails to current_price - 0.75*ATR when 1 ATR in profit, never decreases
- ORB_BREAKOUT: SL moves to entry_price at 1:1 R:R, no further update after
- GAP_FILL/VWAP_RECLAIM: no trailing stop applied
- check_and_execute_exits() never raises — all errors caught

## Deviations from Plan

### Auto-fixed Spec Inconsistency [Rule 1 — spec conflict]

**Found during:** Task B-1 verification
**Issue:** Plan B acceptance criteria says `calculate_quantity(2500, 2450)` returns 20, but formula says cap at 10% of capital. At entry_price=Rs2500, cap=int(10000/2500)=4. min(20, 4)=4, not 20.
**Resolution:** Implemented the formula as written (RESEARCH.md and must_haves truth are authoritative — "capped at 10% capital"). The acceptance criteria example was wrong. Result is 4, not 20.
**Impact:** Correct behavior. Prevents 50% of capital being allocated to one position.

## Known Stubs

None.

## Threat Flags

None.

## Self-Check: PASSED

- execution/order_manager.py exists: FOUND
- Commit 317f559 exists: FOUND
- All acceptance criteria verified via automated test (with mocked IST time for 15:15 gate)
