# Phase 4a: Pre-Market Agents - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.

**Date:** 2026-06-06
**Phase:** 04A-pre-market-agents
**Mode:** discuss (default)
**Areas discussed:** Gemini schema, Gap score formula, AgentI2 batching, AgentI3 strategy assignment

---

## Questions Asked & Answers

### Gemini structured output schema
| Question | Selected |
|----------|----------|
| Pydantic models + strict validation → fallback on failure vs raw JSON parse | **Pydantic models + strict validation → fallback on failure** |

### Gap score formula
| Question | Selected |
|----------|----------|
| `abs(gap_pct) * min(prev_volume/500000, 3.0)` vs multi-factor score | **`gap_score = abs(gap_pct) * min(prev_volume/500000, 3.0)`** |

### AgentI2 news batching
| Question | Selected |
|----------|----------|
| One call per stock (1s delay, UNKNOWN fallback) vs batch all stocks in one call | **One Gemini call per stock, 1s delay, UNKNOWN if no news** |

### AgentI3 strategy assignment
| Question | Selected |
|----------|----------|
| Rule table (gap_pct + bias) → AgentI3 computes price levels vs Gemini assigns strategy | **Rule table: GAP_AND_GO(>3%+BULLISH), ORB_BREAKOUT(>2%+NEUTRAL), GAP_FILL(1.5-3%), VWAP_RECLAIM(<2%). AgentI3 computes entry/SL/target using ATR.** |

---

## Claude's Discretion Items

- Exact Gemini prompt wording
- Gemini client instantiation (module-level vs per-call)
- yfinance `ticker.news` key name for headline text
- NO_TRADE_DAY signal format (empty list vs explicit flag)

---

## Deferred Ideas

- Telegram watchlist notification (v2 / ALRT scope)
- Sector rotation scoring
