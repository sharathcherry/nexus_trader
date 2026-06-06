# Phase 3: Paper Portfolio Engine - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.

**Date:** 2026-06-06
**Phase:** 03-paper-portfolio-engine
**Mode:** discuss (default)
**Areas discussed:** SQLite schema, State persistence, Brokerage calculation placement, PaperPortfolio vs OrderManager split

---

## Questions Asked & Answers

### SQLite schema
| Question | Selected |
|----------|----------|
| Two tables (positions + trades) vs single trades table with status | **Two tables: positions (open only) + trades (all closed)** |

### State persistence
| Question | Selected |
|----------|----------|
| Write-through on every trade vs write on shutdown + periodic flush | **Write-through on every trade** |

### Brokerage calculation placement
| Question | Selected |
|----------|----------|
| Private _calculate_brokerage() inside PaperPortfolio vs standalone brokerage.py | **Private _calculate_brokerage() inside PaperPortfolio** |

### PaperPortfolio vs OrderManager coupling
| Question | Selected |
|----------|----------|
| OrderManager holds reference injected at __init__ vs receives portfolio per-call | **OrderManager holds reference injected at __init__** |

---

## Claude's Discretion Items

- SQLite column types
- sqlite3 direct vs thin connection manager
- Trailing stop exact implementation details (PORT-13 values defined in REQUIREMENTS.md)

---

## Deferred Ideas

None.
