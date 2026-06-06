# Phase 2: Data Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in 02-CONTEXT.md — this log preserves the discussion.

**Date:** 2026-06-06
**Phase:** 02-data-layer
**Mode:** discuss (default)
**Areas discussed:** yfinance fetch pattern, NSE universe storage, Indicator input contract, Error return contract

---

## Questions Asked & Answers

### yfinance fetch pattern
| Question | Options | Selected |
|----------|---------|----------|
| Individual Ticker vs yf.download() batch | Individual Ticker.history() + 0.2s delay / yf.download() + MultiIndex flatten | **Individual Ticker.history() + 0.2s delay** |

**Notes:** CLAUDE.md explicitly flags MultiIndex columns as a breakage risk with yf.download(). Individual calls are simpler and already mandate the 0.2s delay from STATE.md.

### NSE universe storage
| Question | Options | Selected |
|----------|---------|----------|
| Universe format | Hardcoded Python list / JSON file / CSV file | **Hardcoded Python list in data/universe.py** |

**Notes:** Zero dependencies, version-controlled, grep-friendly. Nifty 100 changes ~quarterly so manual update is acceptable.

### Indicator input contract
| Question | Options | Selected |
|----------|---------|----------|
| Who filters session hours? | Caller filters / Indicators filter internally | **Caller filters — Indicators receives clean data** |

**Notes:** get_intraday_candles() returns 09:15+ rows only. Simplifies indicator code and makes each indicator independently testable.

### Error return contract
| Question | Options | Selected |
|----------|---------|----------|
| Return type on failure | None/empty DataFrame/empty dict by type / Always None / Raise exception | **None for scalars, empty DataFrame for tabular, empty dict for multi-value** |

**Notes:** Consistent with Python stdlib. Agents use `if price is None` and `if df is None or df.empty` checks throughout.

---

## Claude's Discretion Items

- EMA implementation detail (`.ewm(span=period)` vs manual)
- Whether Indicators methods are `@staticmethod` or `@classmethod`
- Log message format for 429 / empty DataFrame yfinance responses

---

## Deferred Ideas

None.
