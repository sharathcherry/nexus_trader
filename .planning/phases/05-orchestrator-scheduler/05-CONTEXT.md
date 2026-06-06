# Phase 5: Orchestrator & Scheduler - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire all 8 agents (I0–I3, I4, I6, I9) into a single unattended daily pipeline controlled by `NexusTrader` class and `TradingScheduler`. APScheduler (BackgroundScheduler + ThreadPoolExecutor) runs Mon–Fri on IST schedule: pre-market at 08:30, market session 09:15–15:15 (60s poll), post-market at 15:35. Hardcoded NSE 2026 holiday list skips trading days. Graceful Ctrl+C force-closes positions and saves state. Delivers `main.py` (entry point + banner) and `execution/scheduler.py` (NexusTrader + TradingScheduler).

</domain>

<decisions>
## Implementation Decisions

### NSE Holiday Detection
- **D-01:** Hardcoded 2026 NSE trading holiday set in `config.py` as `NSE_HOLIDAYS_2026: set[str]` — values are `'YYYY-MM-DD'` strings. `config.is_trading_day(date) -> bool` checks `date.weekday() not in (5, 6)` AND `date.strftime('%Y-%m-%d') not in config.NSE_HOLIDAYS_2026`. Zero network dependency, instant check, survives yfinance outages.
- **D-02:** No runtime fetch from nselib/nsepython. Hardcoded list is authoritative for 2026. When 2027 is needed, add `NSE_HOLIDAYS_2027` to config.

### NO_TRADE_DAY Trigger
- **D-03:** NO_TRADE_DAY fires on holiday/weekend only — `not config.is_trading_day(date.today())`. No ^NSEI zero-volume check. Log `"NSE holiday — no trading today"` at INFO and return early from pre-market job. Pipeline does not start.
- **D-04:** No network call in the NO_TRADE_DAY check — avoids false positives from yfinance 429 or pre-market data delays.

### main.py Blocking Strategy & Shutdown
- **D-05:** `shutdown_event = threading.Event()` at module level. Main thread blocks on `shutdown_event.wait()`. `KeyboardInterrupt` caught in `try/except` around the wait.
- **D-06:** Graceful shutdown sequence on `KeyboardInterrupt`:
  1. `portfolio.force_squareoff_all()` — closes all open positions (matches AgentI4's existing contract)
  2. `portfolio.save_state()` — persists state to SQLite
  3. `scheduler.shutdown(wait=False)` — stops APScheduler immediately (no wait for running jobs)
  4. `sys.exit(0)` — clean exit code
- **D-07:** `shutdown_event` can also be set from a scheduled job (e.g., end-of-day cleanup) to trigger the same shutdown sequence.

### NEXUS ASCII Banner
- **D-08:** Hand-crafted block letter ASCII art spelling `NEXUS TRADER`, printed to terminal at `main.py` startup via `print_banner()` function in `main.py`. Uses standard `print()` — no colorlog for the banner itself.
- **D-09:** Below the ASCII art, print a 4-line info block:
  - Capital: `₹{config.CAPITAL:,.0f}` (from config)
  - Date: `{weekday} {YYYY-MM-DD}` (e.g. `Friday 2026-06-06`)
  - Mode: `LIVE` or `DRY-RUN` (based on `--dry-run` CLI flag)
  - API keys: `GEMINI ✓  ANTHROPIC ✓` (or `✗` if key is absent/empty) — confirms keys loaded before pipeline starts

### NexusTrader Class Structure
- **D-10:** `class NexusTrader` in `execution/scheduler.py`. `__init__(self)` instantiates `PaperPortfolio` and all agents (`AgentI0` through `AgentI9`). Three public methods: `run_pre_market_pipeline()`, `run_market_session()`, `run_post_market()`. Each method is the APScheduler job target.
- **D-11:** `class TradingScheduler` wraps `BackgroundScheduler(executors={'default': ThreadPoolExecutor(max_workers=1)})`. Configures three CronTrigger jobs pointing to NexusTrader methods. `max_instances=1` on each job prevents overlap.

### Claude's Discretion
- Exact ASCII art design for `NEXUS TRADER` block letters
- IST timezone object — `pytz.timezone('Asia/Kolkata')` passed to APScheduler
- Exact `CronTrigger` day_of_week parameter for Mon–Fri (`'mon-tue-wed-thu-fri'` or `0-4`)
- Whether `run_market_session()` runs as a single long job or spawns repeated 60s poll jobs

</decisions>

<specifics>
## Specific Ideas

- `shutdown_event.wait()` pattern is cleaner than `while True: time.sleep(1)` — no busy-wait, event can be set from any thread including scheduled jobs.
- `scheduler.shutdown(wait=False)` avoids hanging if a scheduled job (e.g., 60s market poll) is mid-execution when Ctrl+C fires.
- Banner `₹` symbol may not render on all Windows terminals — fallback to `Rs.` if needed (Claude's discretion).

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scheduler patterns
- `CLAUDE.md` §"2. APScheduler" — BackgroundScheduler + ThreadPoolExecutor recommendation, CronTrigger IST pattern, Windows-specific notes, `max_instances=1` rationale

### Agent interfaces (what NexusTrader calls)
- `.planning/phases/04A-pre-market-agents/04A-CONTEXT.md` — AgentI0–I3 run() signatures and return types
- `.planning/phases/04B-market-session-agents/04B-CONTEXT.md` — AgentI4.run(), AgentI6, force_squareoff_all contract
- `.planning/phases/04C-post-market-agent/04C-CONTEXT.md` — AgentI9.run() signature, PaperPortfolio interface

### Portfolio interface
- `.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md` — PaperPortfolio.save_state(), get_daily_report(), force_squareoff_all()

### Requirements
- `.planning/REQUIREMENTS.md` §"Orchestrator & Scheduler" (ORCH-01 through ORCH-07)

### Config constants
- `config.py` — CAPITAL, ANTHROPIC_API_KEY, GEMINI_API_KEY, and NSE_HOLIDAYS_2026 (to be added)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (exist after Phases 1–4c)
- `execution/portfolio.py` → `PaperPortfolio` — instantiated once in `NexusTrader.__init__`, shared across all agents
- `config.py` → `config.CAPITAL`, `config.ANTHROPIC_API_KEY`, `config.GEMINI_API_KEY` — already present
- `utils/logger.py` → `setup_logger(__name__)` — module-level logger pattern
- All agent files (`agents/agent_i0.py` through `agents/agent_i9.py`) — exist after Phases 4a–4c

### Established Patterns
- `from config import config` and `logger = setup_logger(__name__)` at module level (every prior phase)
- Error contract: methods return `None`/empty on failure, never raise to caller
- `BackgroundScheduler` with `ThreadPoolExecutor` — CLAUDE.md §2 explicit recommendation

### Integration Points
- `main.py` → `TradingScheduler` (starts scheduler, blocks on `shutdown_event`)
- `TradingScheduler` → `NexusTrader` (job targets: pre_market, market_session, post_market)
- `NexusTrader` → all 8 agents + `PaperPortfolio`
- `NexusTrader.run_pre_market_pipeline()` → `AgentI0→I1→I2→I3` sequential chain
- `NexusTrader.run_post_market()` → `portfolio.get_daily_report()` → `AgentI9.run(portfolio)`

</code_context>

<deferred>
## Deferred Ideas

- Telegram notification on pipeline start/stop — ALRT-01/v2 scope
- Web dashboard for live P&L monitoring — out of scope
- Auto-restart on crash (systemd/supervisor) — Phase 6+ or deployment concern

</deferred>

---

*Phase: 05-orchestrator-scheduler*
*Context gathered: 2026-06-06*
