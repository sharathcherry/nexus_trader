# Phase 1: Foundation - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Project is runnable with correct dependencies — google-genai SDK wired, config loaded from .env, structured logger active, no deprecated packages. This phase creates the scaffold every subsequent phase builds on: folder structure, config.py, requirements.txt, .env.example, .gitignore, and utils/logger.py. No agent logic, no data fetching, no trading logic.

</domain>

<decisions>
## Implementation Decisions

### Config class pattern
- **D-01:** Plain class singleton — `class Config:` reads all params via `os.getenv()` in `__init__`, module ends with `config = Config()`. Downstream import: `from config import config; config.CAPITAL`.
- **D-02:** No pydantic or dataclass — zero extra dependencies for config. python-dotenv loads .env file before Config is instantiated.

### Missing .env key behavior
- **D-03:** Crash hard on startup — `Config.__init__` raises `ValueError` with a clear message if any required key is absent. All four keys (GEMINI_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) are required. No silent empty strings. Better to fail at startup than silently at 09:00 IST.

### Logger scope in Phase 1
- **D-04:** Basic 3 levels only — `setup_logger()` in `utils/logger.py` configures colorlog with INFO (green), WARNING (yellow), ERROR (red). Terminal handler + rotating file handler to `logs/`. No custom TRADE or P&L levels yet — those are added in Phase 5 when the orchestrator is built.
- **D-05:** Logger creates `logs/` directory if it doesn't exist. Log filename is date-stamped: `logs/nexus_YYYY-MM-DD.log`.

### Package structure
- **D-06:** Flat imports from project root — `config.py` and `main.py` at root. `utils/`, `agents/`, `data/`, `execution/` are sub-directories with `__init__.py` for cross-module imports. Import pattern everywhere: `from config import config`, `from utils.logger import setup_logger`.
- **D-07:** Sub-folders created in Phase 1 as empty scaffolds (with `__init__.py`): `agents/`, `data/`, `execution/`, `utils/`, `logs/`. Agents and data modules are populated in later phases.

### requirements.txt
- **D-08:** `google-generativeai` is ABSENT. `google-genai>=2.0.0` is present (locked decision from STATE.md).
- **D-09:** `ta` library is ABSENT — inline pandas indicators decision made in STATE.md. SCAF-03 listed ta but it's overridden by the architectural decision.
- **D-10:** All other deps pinned: `yfinance==0.2.40`, `pandas>=2.0,<3.0`, `numpy>=1.24`, `APScheduler==3.10.4`, `anthropic>=0.40.0`, `google-genai>=2.0.0`, `colorlog>=6.7`, `tabulate>=0.9`, `pytz>=2024.1`, `python-dotenv>=1.0`.

### Claude's Discretion
- Exact colorlog formatter string (timestamp format, field widths)
- Whether to use `RotatingFileHandler` or `TimedRotatingFileHandler` for log files
- .gitignore additional patterns beyond `.env` (e.g., `__pycache__/`, `*.pyc`, `logs/`)

</decisions>

<specifics>
## Specific Ideas

- Success criterion imports: `python -c "from config import config; print(config.CAPITAL)"` — this exact command must work after Phase 1.
- `google-generativeai` must be absent from requirements.txt — it's a deprecated package; presence would be a test failure.
- .env.example must document all 4 keys: GEMINI_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
- `.env` must be in `.gitignore`.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### SDK deprecation and version decisions
- `.planning/STATE.md` §"Key Decisions Made" — google-genai vs google-generativeai decision, ta library exclusion, all locked architectural decisions
- `CLAUDE.md` §"Technology Stack" — detailed SDK deprecation timeline, correct import patterns for google-genai and anthropic, version pin rationale

### Requirements
- `.planning/REQUIREMENTS.md` §"Scaffolding" (SCAF-01 through SCAF-05) — the 5 requirements this phase must deliver
- `.planning/ROADMAP.md` §"Phase 1: Foundation" — success criteria (4 items) that define done

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — project is a blank slate. Phase 1 creates all assets from scratch.

### Established Patterns
- Import pattern established here flows into every later phase: `from config import config`
- Logger pattern: `logger = setup_logger(__name__)` in each module

### Integration Points
- `config.py` is the single source of truth for all parameters — every subsequent phase imports it
- `utils/logger.py` provides the logger factory — Phase 2+ modules call `setup_logger(__name__)`
- `logs/` directory created here; Phase 4c (AgentI9) writes performance logs to `logs/performance/`

</code_context>

<deferred>
## Deferred Ideas

- Custom TRADE (cyan) and P&L+/- log levels — deferred to Phase 5 (Orchestrator & Scheduler) per ORCH-06
- Telegram notification integration — out of scope for Phase 1; keys documented in .env.example but Telegram logic is Phase 5+

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-06-06*
