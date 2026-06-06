# Phase 4b: Market Session Agents - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-06-06
**Phase:** 04B-market-session-agents
**Mode:** discuss (standard)
**Areas discussed:** Strategy signal conditions, AgentI6 structure, POSSIBLE_CIRCUIT behavior, Partial exit scope

---

## Discussion

### Strategy signal conditions
| Option | Selected |
|--------|----------|
| Pure price trigger — no extra conditions | ✅ |
| Price + VWAP confirmation only | — |
| Strategy-specific confirmations (RSI, volume) | — |

**Decision:** Buy when current_price crosses entry_trigger (direction per strategy). No additional indicator dependency. GAP_AND_GO/ORB/VWAP_RECLAIM: price >= trigger. GAP_FILL: price <= trigger.

### AgentI6 structure
| Option | Selected |
|--------|----------|
| Separate class in agents/agent_i6.py | ✅ |
| Private methods inside AgentI4 | — |
| Both agents started independently by orchestrator | — |

**Decision:** Separate `agents/agent_i6.py`. `monitor_positions()` public method. AgentI4 instantiates AgentI6 in `__init__`. Phase 5 only imports AgentI4.

### POSSIBLE_CIRCUIT behavior
| Option | Selected |
|--------|----------|
| Log WARNING + skip stock for remainder of session | ✅ |
| Log WARNING only | — |
| Log WARNING + halt all new entries system-wide | — |

**Decision:** Add to `circuit_set`. Skip both entry checks and exit checks for that symbol for remainder of session. `circuit_set` shared between AgentI4 and AgentI6.

### Partial exit scope
| Option | Selected |
|--------|----------|
| GAP_AND_GO + ORB_BREAKOUT only | ✅ |
| All 4 strategies | — |
| GAP_AND_GO + ORB_BREAKOUT + VWAP_RECLAIM | — |

**Decision:** GAP_FILL and VWAP_RECLAIM hold for full target. Only momentum strategies (GAP_AND_GO, ORB_BREAKOUT) exit 50% at 1:1 R:R then trail.

---

## Claude's Discretion Items
- Exact log message format for trade events
- Live positions table printed each cycle (tabulate)
- deque maxlen and price tracking data structure internals

---

## Deferred Ideas
- RSI/volume signal confirmations → backlog
- Re-entry logic after partial exit → v2

---

*Log written: 2026-06-06*
