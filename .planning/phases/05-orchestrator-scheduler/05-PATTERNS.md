# Phase 5: Orchestrator & Scheduler - Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 3 (2 new files + 1 modified file)
**Analogs found:** 3 / 3 (all files have analogs in existing source or verified plan files)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `execution/scheduler.py` | orchestrator + scheduler | event-driven (APScheduler) | `main.py` (module structure) + `04B-01-PLAN.md` AgentI6 class skeleton | role-match (same project; no orchestrator file exists yet) |
| `main.py` | entry-point | request-response (CLI → blocking loop) | `main.py` current stub (lines 1–13) | exact-replacement (file exists as stub; Phase 5 rewrites it) |
| `config.py` additions | config | static-lookup | `config.py` existing `Config` class (lines 7–57) | exact (same file, additive change) |

---

## Pattern Assignments

### `execution/scheduler.py` (orchestrator + scheduler, event-driven)

**Primary analog:** `main.py` lines 1–13 (import/logger pattern)
**Secondary analog:** `04B-01-PLAN.md` AgentI6 class skeleton (class structure with `__init__` + public methods)
**Tertiary analog:** `04C-PATTERNS.md` agent class conventions (constructor injection, `_private` attributes, `return None` on failure)

**Note on analog availability:** `execution/` contains only `__init__.py` (empty). No orchestrator or scheduler `.py` file exists. Patterns are derived from: `config.py`, `utils/logger.py`, `main.py` (all three existing source files), and agent class skeletons from `04A-PLAN-A.md`/`04B-01-PLAN.md`.

---

#### Imports pattern

**Source:** `main.py` lines 1–4 + `04C-PATTERNS.md` imports section + `05-RESEARCH.md` TradingScheduler skeleton

```python
from __future__ import annotations

import threading
from datetime import datetime
from typing import TYPE_CHECKING

import pytz
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from config import config
from utils.logger import setup_logger

if TYPE_CHECKING:
    from execution.portfolio import PaperPortfolio

logger = setup_logger(__name__)
ist = pytz.timezone('Asia/Kolkata')
```

Key conventions (consistent across all prior phases):
- `from config import config` — always the module singleton, never `import config`
- `logger = setup_logger(__name__)` — module-level singleton, never per-call
- `from __future__ import annotations` — enables deferred annotation evaluation (used in 04C)
- `TYPE_CHECKING` guard for circular/heavy imports used only in type hints
- Module-level `ist = pytz.timezone('Asia/Kolkata')` constant — shared by both classes in the file

---

#### Agent import block

**Source:** `05-CONTEXT.md` §"Integration Points" + `04A-PLAN-A.md` agent names

```python
from agents.agent_i0 import AgentI0
from agents.agent_i1 import AgentI1
from agents.agent_i2 import AgentI2
from agents.agent_i3 import AgentI3
from agents.agent_i4 import AgentI4
from agents.agent_i6 import AgentI6
from agents.agent_i9 import AgentI9
from execution.portfolio import PaperPortfolio
```

Note: AgentI5 and AgentI7/I8 are not listed in the CONTEXT.md integration map (I0–I3, I4, I6, I9). Import only the seven named agents. Verify the full list against the actual agent files when they exist.

---

#### `NexusTrader` class `__init__` pattern

**Source:** `04C-PATTERNS.md` §"Class `__init__` pattern" (AgentI9 constructor conventions) + `05-RESEARCH.md` dry-run injection pattern (lines 388–400)

```python
class NexusTrader:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._portfolio = PaperPortfolio()
        self._agent_i0 = AgentI0()
        self._agent_i1 = AgentI1()
        self._agent_i2 = AgentI2()
        self._agent_i3 = AgentI3()
        self._agent_i4 = AgentI4()
        self._agent_i6 = AgentI6()
        self._agent_i9 = AgentI9(portfolio=self._portfolio)
        logger.info('NexusTrader initialised — dry_run=%s', dry_run)
```

Conventions from prior phases:
- Agent constructor arguments: most agents take no args; AgentI9 receives `portfolio` (per `04C-PATTERNS.md`)
- Private attributes prefixed with `_` (e.g., `self._portfolio`, `self._agent_i0`)
- `dry_run` is public (`self.dry_run`) since it is readable from any method
- Log at INFO on successful init (mirrors `utils/logger.py` conventions)

---

#### `NexusTrader` public method pattern (three pipeline entry-points)

**Source:** `05-RESEARCH.md` §"run_pre_market_pipeline Holiday Guard" + `05-CONTEXT.md` D-10 + `04C-PATTERNS.md` §"Public method signature pattern"

```python
def run_pre_market_pipeline(self) -> None:
    """Pre-market scan: AgentI0 → I1 → I2 → I3. Returns early on NSE holiday."""
    try:
        today = datetime.now(ist).date()
        if not config.is_trading_day(today):
            logger.info('NSE holiday — no trading today (%s)', today)
            return
        # ... sequential I0 → I1 → I2 → I3 chain ...
    except Exception as e:
        logger.error('run_pre_market_pipeline crashed: %s', e, exc_info=True)

def run_market_session(self) -> None:
    """Market session poll: AgentI4 signals → AgentI6 position monitor."""
    try:
        # ... I4 + I6 calls ...
        if self.dry_run:
            logger.info('[DRY-RUN] signals generated — order placement skipped')
            return
        # ... actual order placement via portfolio ...
    except Exception as e:
        logger.error('run_market_session crashed: %s', e, exc_info=True)

def run_post_market(self) -> None:
    """Post-market review: get_daily_report → AgentI9."""
    try:
        # ... portfolio.get_daily_report() → agent_i9.run(portfolio) ...
    except Exception as e:
        logger.error('run_post_market crashed: %s', e, exc_info=True)
```

Critical conventions:
- All three methods return `None` — never raise to the APScheduler caller
- Each method is wrapped in a top-level `try/except Exception` — log and return on crash so the BackgroundScheduler thread survives (per `05-RESEARCH.md` §"Known Threat Patterns")
- `datetime.now(ist).date()` for holiday check — NOT `date.today()` (avoids UTC clock issue, per `05-RESEARCH.md` Pitfall 6)
- Docstring on all public methods

---

#### `TradingScheduler` class pattern

**Source:** `05-RESEARCH.md` §"Complete TradingScheduler Class Skeleton" (lines 476–546) — fully verified against APScheduler 3.10.4

```python
class TradingScheduler:
    def __init__(self, nexus_trader: NexusTrader) -> None:
        self._trader = nexus_trader
        self._scheduler = BackgroundScheduler(
            executors={'default': ThreadPoolExecutor(max_workers=1)},
            timezone=ist,
        )
        self._configure_jobs()

    def _configure_jobs(self) -> None:
        self._scheduler.add_job(
            self._trader.run_pre_market_pipeline,
            CronTrigger(day_of_week='mon-fri', hour=8, minute=30, timezone=ist),
            id='pre_market',
            name='Pre-market scan',
            max_instances=1,        # on add_job(), NOT scheduler constructor
            misfire_grace_time=300,
        )
        market_trigger = OrTrigger([
            CronTrigger(day_of_week='mon-fri', hour=9,       minute='15-59', timezone=ist),
            CronTrigger(day_of_week='mon-fri', hour='10-14', minute='*',     timezone=ist),
            CronTrigger(day_of_week='mon-fri', hour=15,      minute='0-15',  timezone=ist),
        ])
        self._scheduler.add_job(
            self._trader.run_market_session,
            market_trigger,
            id='market_session',
            name='Market session poll',
            max_instances=1,
            misfire_grace_time=60,
        )
        self._scheduler.add_job(
            self._trader.run_post_market,
            CronTrigger(day_of_week='mon-fri', hour=15, minute=35, timezone=ist),
            id='post_market',
            name='Post-market review',
            max_instances=1,
            misfire_grace_time=300,
        )

    def start(self) -> None:
        self._scheduler.start()
        logger.info('TradingScheduler started — 3 jobs configured')

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)   # wait=False prevents hang on Windows
        logger.info('TradingScheduler stopped')
```

Critical: `max_instances=1` goes on `add_job()`, NOT the `BackgroundScheduler()` constructor — constructor kwarg is silently ignored (per `05-RESEARCH.md` Pitfall 1).

---

### `main.py` (entry-point, request-response + blocking loop)

**Analog:** Current `main.py` stub (lines 1–13) — this file is a complete rewrite

**Current stub** (`main.py` lines 1–13):
```python
from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    logger.info("nexus_trader starting up (placeholder — Phase 5 adds full orchestrator)")
    logger.info(f"Capital: ₹{config.CAPITAL:,}")


if __name__ == "__main__":
    main()
```

Phase 5 replaces this with the full entry-point. Follow the import/logger pattern from the stub; replace the `main()` body entirely.

---

#### Imports pattern for `main.py`

**Source:** `main.py` lines 1–4 (existing) + `05-RESEARCH.md` §"main.py Blocking + Shutdown Skeleton"

```python
import argparse
import sys
import threading

from config import config
from utils.logger import setup_logger
from execution.scheduler import NexusTrader, TradingScheduler

logger = setup_logger(__name__)
shutdown_event = threading.Event()
```

Convention: `shutdown_event` is module-level so scheduled jobs can set it from a background thread (per `05-CONTEXT.md` D-07).

---

#### `parse_args()` pattern

**Source:** `05-RESEARCH.md` §"argparse in main.py" (lines 360–376, verified in Python 3.12)

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='nexus_trader — NSE intraday paper trading pipeline'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Run pipeline without placing any orders (agents execute, orders skipped)'
    )
    return parser.parse_args()
```

`args.dry_run` is `False` by default; `True` when `--dry-run` flag is passed. No other CLI flags in this phase.

---

#### `print_banner()` pattern

**Source:** `05-CONTEXT.md` D-08 + D-09. No codebase analog — first banner in project.

```python
def print_banner(dry_run: bool = False) -> None:
    """Print ASCII art banner + 4-line info block to stdout."""
    # ASCII art block letters spelling NEXUS TRADER (hand-crafted — Claude's discretion)
    # Uses print() directly — NOT colorlog (per D-08)
    print("""
  _   _ _______  ___  _   _ _____ 
 | \\ | | ____\\ \\/ / || | | |_   _|
 |  \\| |  _|  \\  /| || | | | | |  
 | |\\  | |___ /  \\| |_| |_| | | |  
 |_| \\_|_____/_/\\_\\\\___/\\___/  |_|  
 _____ ____      _    ____  _____ ____  
|_   _|  _ \\   / \\  |  _ \\| ____|  _ \\ 
  | | | |_) | / _ \\ | | | |  _| | |_) |
  | | |  _ < / ___ \\| |_| | |___|  _ < 
  |_| |_| \\_/_/   \\_\\____/|_____|_| \\_\\
    """)

    from datetime import datetime
    import pytz
    today = datetime.now(pytz.timezone('Asia/Kolkata'))
    date_str = today.strftime('%A %Y-%m-%d')
    mode_str = 'DRY-RUN' if dry_run else 'LIVE'

    # API key presence check — show only ✓/✗, never key value (per security rules)
    gemini_ok  = '✓' if config.GEMINI_API_KEY    else '✗'
    claude_ok  = '✓' if config.ANTHROPIC_API_KEY else '✗'

    print(f'  Capital : Rs.{config.CAPITAL:,.0f}')   # Rs. fallback for ₹ render issues
    print(f'  Date    : {date_str}')
    print(f'  Mode    : {mode_str}')
    print(f'  API keys: GEMINI {gemini_ok}  ANTHROPIC {claude_ok}')
    print()
```

Notes on implementation:
- The exact ASCII art design is Claude's discretion (per `05-CONTEXT.md` §"Claude's Discretion")
- Use `Rs.` as default capital prefix — `₹` (U+20B9) may render as `?` in Windows cmd.exe if code page is not UTF-8 (per `05-RESEARCH.md` Pitfall 4). Safe alternative: call `sys.stdout.reconfigure(encoding='utf-8')` before `print_banner()` then use `₹`
- Never print the actual key value — only presence/absence (per `05-RESEARCH.md` §"Known Threat Patterns")

---

#### `main()` blocking + shutdown pattern

**Source:** `05-RESEARCH.md` §"main.py Blocking + Shutdown Skeleton" (lines 549–577, verified)

```python
def main() -> None:
    args = parse_args()
    print_banner(dry_run=args.dry_run)

    trader = NexusTrader(dry_run=args.dry_run)    # instantiate BEFORE TradingScheduler
    scheduler = TradingScheduler(nexus_trader=trader)
    scheduler.start()

    logger.info('nexus_trader running — press Ctrl+C to stop')
    try:
        shutdown_event.wait()     # blocks indefinitely; no busy-wait
    except KeyboardInterrupt:
        print('\nCtrl+C — shutting down...')
        trader._portfolio.force_squareoff_all()
        trader._portfolio.save_state()
        scheduler.shutdown()
        sys.exit(0)


if __name__ == '__main__':
    main()
```

Critical ordering: instantiate `NexusTrader` fully BEFORE creating `TradingScheduler` — avoids the Pitfall 5 race condition (per `05-RESEARCH.md` Pitfall 5) where a job fires before the trader is ready.

---

### `config.py` additions (config, static-lookup)

**Analog:** `config.py` existing `Config` class — additive change, same file

**Existing `config.py`** structure (`config.py` lines 1–57):
- `load_dotenv()` at module level (line 4)
- `class Config` with `__init__` setting all constants as `self.ATTR = value`
- `_require(key)` private helper for mandatory env vars
- `config = Config()` singleton at bottom (line 57)

---

#### `NSE_HOLIDAYS_2026` addition pattern

**Source:** `05-RESEARCH.md` §"NSE 2026 Holiday List" + `config.py` lines 7–57

Add `NSE_HOLIDAYS_2026` as a **class-level attribute** (not instance attribute), since it is a static constant that does not vary per instance and requires no `__init__` logic:

```python
class Config:
    # Class-level static constant — defined before __init__
    NSE_HOLIDAYS_2026: set[str] = {
        "2026-01-15",  # Maharashtra Municipal Corporation Election
        "2026-01-26",  # Republic Day
        "2026-03-03",  # Holi
        "2026-03-26",  # Shri Ram Navami
        "2026-03-31",  # Shri Mahavir Jayanti
        "2026-04-03",  # Good Friday
        "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
        "2026-05-01",  # Maharashtra Day
        "2026-05-28",  # Bakri Id (Eid ul-Adha)
        "2026-06-26",  # Muharram
        "2026-09-14",  # Ganesh Chaturthi
        "2026-10-02",  # Mahatma Gandhi Jayanti
        "2026-10-20",  # Dussehra
        "2026-11-10",  # Diwali — Balipratipada
        "2026-11-24",  # Guru Nanak Jayanti (Prakash Gurpurb)
        "2026-12-25",  # Christmas
    }

    def __init__(self):
        # ... existing __init__ body unchanged ...
```

This follows Python convention for constants that belong to a class but don't depend on instance state. It is accessible as `config.NSE_HOLIDAYS_2026` (via the singleton) or `Config.NSE_HOLIDAYS_2026` (via the class directly).

---

#### `is_trading_day()` addition pattern

**Source:** `05-RESEARCH.md` §"is_trading_day() implementation" (verified with runtime tests)

Add as a **method on `Config`** (not a standalone module-level function) to keep all config logic co-located and accessible via the `config` singleton:

```python
# Add to Config class — place after __init__
def is_trading_day(self, d) -> bool:
    """Return True if d is a weekday and not in NSE_HOLIDAYS_2026.

    Args:
        d: datetime.date object (use datetime.now(ist).date(), not date.today())
    """
    return (
        d.weekday() not in (5, 6)
        and d.strftime('%Y-%m-%d') not in self.NSE_HOLIDAYS_2026
    )
```

Usage in `execution/scheduler.py`:
```python
from datetime import datetime
import pytz

ist = pytz.timezone('Asia/Kolkata')

# Inside NexusTrader.run_pre_market_pipeline():
today = datetime.now(ist).date()
if not config.is_trading_day(today):
    logger.info('NSE holiday — no trading today (%s)', today)
    return
```

Required import addition at top of `config.py` — add `from datetime import date as _date` if type annotations are used in the method signature. The `_date` alias avoids shadowing the built-in `date` name with the parameter name `d`.

---

#### Test file additions

**Source:** `05-RESEARCH.md` §"Validation Architecture" + `02-PATTERNS.md` §"No Analog Found" (tests section)

Phase 5 creates four new test files. No test files currently exist in the codebase. Follow the pytest conventions established in `02-PATTERNS.md`:

```python
# tests/__init__.py — empty, same convention as agents/__init__.py and execution/__init__.py

# pytest.ini (project root)
[pytest]
testpaths = tests
```

Mock pattern for scheduler tests (per `05-RESEARCH.md` §"Recommended mock targets"):
```python
from unittest.mock import MagicMock, patch

def test_pre_market_pipeline_sequence():
    with patch('execution.scheduler.AgentI0') as MockI0, \
         patch('execution.scheduler.AgentI1') as MockI1, \
         patch('execution.scheduler.AgentI2') as MockI2, \
         patch('execution.scheduler.AgentI3') as MockI3, \
         patch('execution.scheduler.PaperPortfolio'):
        trader = NexusTrader(dry_run=False)
        trader.run_pre_market_pipeline()
        MockI0.return_value.run.assert_called_once()
```

Scheduler config-inspection pattern — do NOT call `scheduler.start()` in tests:
```python
def test_scheduler_job_ids():
    trader = MagicMock()
    ts = TradingScheduler(nexus_trader=trader)
    job_ids = {job.id for job in ts._scheduler.get_jobs()}
    assert job_ids == {'pre_market', 'market_session', 'post_market'}
```

---

## Shared Patterns

### Logger instantiation
**Source:** `utils/logger.py` lines 9–54 + `main.py` lines 1–4
**Apply to:** `execution/scheduler.py`, `main.py` (already follows this)

```python
from utils.logger import setup_logger
logger = setup_logger(__name__)
```

`setup_logger(__name__)` is idempotent (checks `logger.handlers` before adding). Returns a logger with colored terminal output and 30-day rotating file handler at `logs/nexus_YYYY-MM-DD.log`.

### Config access
**Source:** `config.py` lines 1–57 + pattern from all prior phase PATTERNS.md files
**Apply to:** `execution/scheduler.py`, `main.py`

```python
from config import config
# Access: config.CAPITAL, config.is_trading_day(d), config.NSE_HOLIDAYS_2026
#         config.GEMINI_API_KEY, config.ANTHROPIC_API_KEY
```

Never import individual attributes — always import `config` and access via dot notation.

### Return-None-on-failure contract
**Source:** `04C-PATTERNS.md` §"Return-None-on-failure contract" + `04A-PLAN-A.md` AgentI0 spec
**Apply to:** All three `NexusTrader` public methods

Every NexusTrader public method must:
1. Be wrapped in `try/except Exception as e`
2. Call `logger.error(...)` before any early return on failure
3. Return `None` (implicitly) — never raise to APScheduler
4. Leave the BackgroundScheduler thread alive after any crash

### IST timezone constant
**Source:** `05-RESEARCH.md` §"Scheduler Instantiation"
**Apply to:** `execution/scheduler.py` (shared by NexusTrader and TradingScheduler)

```python
import pytz
ist = pytz.timezone('Asia/Kolkata')
```

Define once at module level; pass to `BackgroundScheduler(timezone=ist)` and all `CronTrigger(timezone=ist)` calls. Do not instantiate `pytz.timezone()` multiple times.

### Path + directory creation
**Source:** `utils/logger.py` line 34 + `04C-PATTERNS.md` §"Path + directory creation"
**Apply to:** Any file that creates output directories (not directly needed in scheduler.py or main.py, but noted for consistency)

```python
from pathlib import Path
Path("logs").mkdir(exist_ok=True)
# parents=True for nested directories; exist_ok=True makes it idempotent
```

---

## Conflicts and Gaps

### Gap 1: Agent constructor signatures not confirmed
**Risk:** `04A-PLAN-A.md` and `04B-01-PLAN.md` exist as plan files but the agent `.py` files have not been written yet (agents directory contains only `__init__.py`). The exact constructor signatures of AgentI0–AgentI3, AgentI4, and AgentI6 are planned but not verified from compiled source.

**Planner action:** Before writing `NexusTrader.__init__`, read the actual agent files once they exist (Phases 4A/4B execution). The `04C-PATTERNS.md` §"Class `__init__` pattern" establishes that agents receiving `portfolio` pass it as a constructor argument (`AgentI9(portfolio=self._portfolio)`). Agents that do not need the portfolio (I0–I4, I6) likely take no constructor args per plan files.

### Gap 2: `portfolio._portfolio` vs `portfolio.portfolio` attribute name
**Risk:** `05-RESEARCH.md` shutdown skeleton uses `trader.portfolio.force_squareoff_all()` (public), but the `NexusTrader.__init__` pattern above uses `self._portfolio` (private). The shutdown code in `main.py` must use the correct accessor.

**Planner action:** Either expose a public `portfolio` property on `NexusTrader`, or access `trader._portfolio` in `main.py`. Consistent with project convention of private `_` prefix for injected dependencies — recommend adding a `@property def portfolio(self) -> PaperPortfolio: return self._portfolio` to `NexusTrader`.

### Gap 3: `PaperPortfolio` constructor signature unknown
**Risk:** `execution/portfolio.py` does not exist yet (Phase 3). `PaperPortfolio()` may require arguments (e.g., `capital=config.CAPITAL`).

**Planner action:** Read `execution/portfolio.py` before writing `NexusTrader.__init__`. If `PaperPortfolio` requires `capital`, use `PaperPortfolio(capital=config.CAPITAL)`.

### Gap 4: `₹` symbol rendering on Windows
**Risk:** The Windows console may not render `₹` (U+20B9) if the code page is not UTF-8, producing `?` or `UnicodeEncodeError`.

**Planner action:** Add `sys.stdout.reconfigure(encoding='utf-8')` as the first line in `main()` before `print_banner()`. If that call fails (older Python), fall back to `Rs.` prefix in the banner info block. Default to `Rs.` in the banner capital line (conservative) unless `sys.stdout.encoding.lower() == 'utf-8'`.

### Gap 5: No existing test infrastructure
**Risk:** `tests/` directory does not exist. `pytest.ini` does not exist. Wave 0 of Phase 5 must create this scaffolding before implementation begins.

**Planner action:** Wave 0 creates: `tests/__init__.py` (empty), `pytest.ini` (root), and all four test file stubs (`test_config.py`, `test_orchestrator.py`, `test_scheduler.py`, `test_main.py`). Same `__init__.py` convention as `agents/__init__.py` and `execution/__init__.py` (empty single-line files).

---

## No Analog Found

All Phase 5 files have analogs (source files or verified plan files). No file is completely pattern-free.

| File | Role | Data Flow | Reason |
|---|---|---|---|
| — | — | — | All patterns covered by existing source + prior PATTERNS.md files |

The only "no-codebase-analog" situation is the APScheduler integration itself — but `05-RESEARCH.md` provides fully verified code for all APScheduler patterns (tested in project venv), which serves as the authoritative reference.

---

## Key Implementation Notes for Planner

1. **Instantiation order in `main.py`:** `NexusTrader` must be fully constructed before `TradingScheduler` is created. Do not call `scheduler.start()` inside `TradingScheduler.__init__` — keep it a separate `scheduler.start()` call in `main()`. This avoids the Pitfall 5 race condition.

2. **`max_instances=1` placement:** Always on `add_job()`, never on the `BackgroundScheduler()` constructor. Constructor kwarg is silently ignored (APScheduler 2.x legacy behavior). Runtime test confirms `job.max_instances` only reflects the `add_job` param.

3. **`scheduler.shutdown(wait=False)` on Windows:** Required in the `KeyboardInterrupt` handler. `wait=True` (default) will hang if a market session job is mid-execution when Ctrl+C fires — no SIGTERM on Windows.

4. **`datetime.now(ist).date()` not `date.today()`:** Holiday check in `run_pre_market_pipeline()` must use IST-localised date. Machines set to UTC will return the wrong date at 23:45 UTC (= 05:15 next-day IST).

5. **`is_trading_day()` as a method on `Config`:** Keeps all config logic co-located. Accessible as `config.is_trading_day(d)` via the singleton. Consistent with the `_require()` private method pattern already in `Config`.

6. **NSE 2026 holiday set as class-level attribute:** `NSE_HOLIDAYS_2026` is static data — define it at class level (above `__init__`), not inside `__init__`. This matches the project convention where pure-data constants are not instance state.

7. **Test file scaffold is Wave 0 deliverable:** All four test files must exist (even as stubs) before implementation begins, per `05-RESEARCH.md` §"Wave 0 Gaps". The `pytest.ini` file configures `testpaths = tests`.

8. **`AgentI5`, `AgentI7`, `AgentI8` are not in Phase 5:** CONTEXT.md integration map lists only I0–I3, I4, I6, I9. Do not import or instantiate any agents outside this list.

---

## Metadata

**Analog search scope:** `C:\Users\katuk\OneDrive\Desktop\projects\stockss` (all `.py` files + planning docs)
**Source files scanned:** `config.py`, `utils/logger.py`, `main.py`, `agents/__init__.py`, `execution/__init__.py`
**Plan files referenced:** `04A-PLAN-A.md`, `04B-01-PLAN.md`, `04C-PATTERNS.md`, `02-PATTERNS.md`
**Research files referenced:** `05-RESEARCH.md`, `05-CONTEXT.md`
**Pattern extraction date:** 2026-06-06
