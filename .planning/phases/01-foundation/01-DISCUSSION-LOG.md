# Phase 1: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-06-06
**Phase:** 01-foundation
**Mode:** discuss (standard)
**Areas discussed:** Config class pattern, Logger scope in Phase 1, Package structure, Missing .env key behavior

---

## Discussion

### Config class pattern
| Option | Selected |
|--------|----------|
| Plain class singleton (`class Config:` + `config = Config()`) | ✅ |
| Pydantic BaseSettings | — |
| Module-level constants | — |

**Decision:** Plain class singleton. Zero extra dependencies. Matches `from config import config; config.CAPITAL` success criterion.

### Logger scope in Phase 1
| Option | Selected |
|--------|----------|
| Basic 3 levels now, custom levels in Phase 5 | ✅ |
| Full logger with all custom levels now | — |
| Single utility function, no custom levels | — |

**Decision:** INFO/WARNING/ERROR with colorlog now. TRADE (cyan) and P&L+/- custom levels deferred to Phase 5 (ORCH-06 requirement).

### Package structure
| Option | Selected |
|--------|----------|
| Flat imports from project root | ✅ |
| Proper package (`nexus_trader/` as the package) | — |
| Flat with no `__init__.py` files | — |

**Decision:** Root-level `config.py`, `main.py`. Sub-folders (`agents/`, `data/`, `execution/`, `utils/`) with `__init__.py`. All imports use short paths: `from config import config`.

### Missing .env key behavior
| Option | Selected |
|--------|----------|
| Crash hard — ValueError for all 4 required keys | ✅ |
| Warn and continue with empty string | — |
| Warn for optional (Telegram), crash for required (API keys) | — |

**Decision:** All 4 keys (GEMINI_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) are required. Config raises ValueError with clear message if any are missing. Fail at startup, not at 09:00 IST.

---

## Claude's Discretion Items

- Colorlog formatter string (timestamp format, field widths)
- File handler type (RotatingFileHandler vs TimedRotatingFileHandler)
- Additional .gitignore patterns beyond `.env`

---

## Deferred Ideas

- Custom TRADE/P&L log levels → Phase 5
- Telegram notification logic → Phase 5+

---

*Log written: 2026-06-06*
