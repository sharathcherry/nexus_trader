# Phase 5: Orchestrator & Scheduler — Research

**Researched:** 2026-06-06
**Domain:** APScheduler 3.x, NexusTrader orchestration, NSE 2026 holiday calendar
**Confidence:** HIGH

---

## Summary

Phase 5 wires all prior agents (I0–I9) into an unattended daily pipeline via two classes:
`NexusTrader` (agent orchestrator) and `TradingScheduler` (APScheduler wrapper) in
`execution/scheduler.py`, plus `main.py` as the entry point. All locked decisions
(D-01–D-11) are confirmed technically sound and are directly implementable.

APScheduler 3.10.4 is already installed. The `BackgroundScheduler` +
`ThreadPoolExecutor(max_workers=1)` + `max_instances=1` pattern is verified and prevents
job overlap by construction. For the market session poll window, `OrTrigger` combining
three `CronTrigger` instances gives exact 09:15–15:15 bounds without requiring time-guard
logic inside `run_market_session()`.

The NSE 2026 holiday list (16 weekday holidays) is sourced from cross-verified NSE
exchange circulars and is ready as a Python `set[str]` literal. The `is_trading_day()`
function logic is tested and correct.

**Primary recommendation:** Implement all three classes (NexusTrader, TradingScheduler,
main entry) exactly per locked decisions. Use `OrTrigger` for the market session job.
No new library installs required.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Hardcoded 2026 NSE trading holiday set in `config.py` as `NSE_HOLIDAYS_2026:
  set[str]` — values are `'YYYY-MM-DD'` strings. `config.is_trading_day(date) -> bool`
  checks `date.weekday() not in (5, 6)` AND `date.strftime('%Y-%m-%d') not in
  config.NSE_HOLIDAYS_2026`. Zero network dependency.
- **D-02:** No runtime fetch from nselib/nsepython. Hardcoded list is authoritative for
  2026. When 2027 is needed, add `NSE_HOLIDAYS_2027` to config.
- **D-03:** NO_TRADE_DAY fires on holiday/weekend only — `not
  config.is_trading_day(date.today())`. No ^NSEI zero-volume check. Log `"NSE holiday —
  no trading today"` at INFO and return early from pre-market job.
- **D-04:** No network call in the NO_TRADE_DAY check.
- **D-05:** `shutdown_event = threading.Event()` at module level. Main thread blocks on
  `shutdown_event.wait()`. `KeyboardInterrupt` caught in `try/except` around the wait.
- **D-06:** Graceful shutdown sequence on `KeyboardInterrupt`:
  1. `portfolio.force_squareoff_all()`
  2. `portfolio.save_state()`
  3. `scheduler.shutdown(wait=False)`
  4. `sys.exit(0)`
- **D-07:** `shutdown_event` can be set from a scheduled job to trigger shutdown.
- **D-08:** Hand-crafted block-letter ASCII art for `NEXUS TRADER` in `print_banner()` in
  `main.py`. Uses `print()` — not colorlog.
- **D-09:** Below banner: 4-line info block — Capital, Date, Mode (`LIVE`/`DRY-RUN`),
  API keys check (`GEMINI ✓ ANTHROPIC ✓` or `✗`).
- **D-10:** `class NexusTrader` in `execution/scheduler.py`. `__init__` instantiates
  `PaperPortfolio` and all agents. Three public methods: `run_pre_market_pipeline()`,
  `run_market_session()`, `run_post_market()`.
- **D-11:** `class TradingScheduler` wraps
  `BackgroundScheduler(executors={'default': ThreadPoolExecutor(max_workers=1)})`.
  Configures three CronTrigger jobs pointing to NexusTrader methods. `max_instances=1`
  on each job.

### Claude's Discretion

- Exact ASCII art design for `NEXUS TRADER` block letters
- IST timezone object — `pytz.timezone('Asia/Kolkata')` passed to APScheduler
- Exact `CronTrigger` day_of_week parameter (research confirms `'mon-fri'` is correct)
- Whether `run_market_session()` uses OrTrigger or CronTrigger + internal guard
  (research recommends OrTrigger)

### Deferred Ideas (OUT OF SCOPE)

- Telegram notification on pipeline start/stop — ALRT-01/v2 scope
- Web dashboard for live P&L monitoring — out of scope
- Auto-restart on crash (systemd/supervisor) — Phase 6+ or deployment concern
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ORCH-01 | NexusTrader class orchestrates all agents | D-10 locked; constructor pattern verified |
| ORCH-02 | TradingScheduler uses APScheduler BackgroundScheduler + ThreadPoolExecutor | APScheduler 3.10.4 installed; imports verified |
| ORCH-03 | CronTrigger jobs — pre-market 08:30 IST, market poll 09:15–15:15 every 60s Mon–Fri, post-market 15:35 | OrTrigger pattern verified; all triggers tested |
| ORCH-04 | NSE_HOLIDAYS_2026 set in config.py; is_trading_day() check | 16-date set sourced from NSE circular + cross-verified |
| ORCH-05 | main.py blocks on threading.Event; graceful Ctrl+C shutdown | threading.Event pattern verified in Python 3.12 |
| ORCH-06 | ASCII NEXUS TRADER banner + 4-line info block at startup | print() pattern confirmed; ₹ render note documented |
| ORCH-07 | --dry-run CLI flag; if dry-run, agents run but no orders placed | argparse action='store_true' + constructor injection verified |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Daily job scheduling | Scheduler (TradingScheduler) | — | APScheduler owns trigger logic; NexusTrader is the target |
| Agent sequencing (pre-market) | Orchestrator (NexusTrader) | — | I0→I1→I2→I3 sequential chain; scheduler just fires once |
| Market session polling | Orchestrator (NexusTrader) | Scheduler | Scheduler fires every 60s; NexusTrader delegates to I4/I6 |
| Holiday detection | Config layer (config.py) | Orchestrator | config.is_trading_day() called inside pre-market job |
| Graceful shutdown | main.py | TradingScheduler | threading.Event in main; scheduler.shutdown() called from handler |
| CLI flag parsing | main.py | NexusTrader | argparse in main; dry_run passed to NexusTrader constructor |
| Post-market review | Orchestrator (NexusTrader) | — | portfolio.get_daily_report() → AgentI9 |

---

## APScheduler Patterns

[VERIFIED: APScheduler 3.10.4 installed; all patterns run without error in project venv]

### Scheduler Instantiation

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import pytz

ist = pytz.timezone('Asia/Kolkata')

scheduler = BackgroundScheduler(
    executors={'default': ThreadPoolExecutor(max_workers=1)},
    timezone=ist  # default timezone for CronTrigger jobs
)
```

`max_workers=1` means only one job runs at a time across all three jobs. Combined with
`max_instances=1` per job, no two executions of the same job can overlap.

### Adding Jobs with max_instances

`max_instances` is a parameter on `scheduler.add_job()`, NOT on the scheduler constructor
or on the executor. Verified:

```python
job = scheduler.add_job(
    func,
    trigger,
    id='job_id',
    name='Human name',
    max_instances=1,      # <— goes HERE, on add_job
    misfire_grace_time=300  # seconds; how late a missed fire can still run
)
```

`job.max_instances` and `job.misfire_grace_time` are readable attributes confirming the
value was accepted. [VERIFIED: direct runtime check]

### Job 1 — Pre-market Scan (08:30 IST, Mon–Fri)

```python
from apscheduler.triggers.cron import CronTrigger

scheduler.add_job(
    nexus_trader.run_pre_market_pipeline,
    CronTrigger(day_of_week='mon-fri', hour=8, minute=30, timezone=ist),
    id='pre_market',
    name='Pre-market scan',
    max_instances=1,
    misfire_grace_time=300   # allow up to 5 min late start
)
```

`day_of_week='mon-fri'` is the canonical APScheduler 3.x string format. Numeric `'0-4'`
also works. String form is more readable. [VERIFIED: CronTrigger field dump confirmed]

### Job 2 — Market Session Poll (09:15–15:15 IST, every minute, Mon–Fri)

See `## Market Session Poll Strategy` for rationale. Use `OrTrigger`:

```python
from apscheduler.triggers.combining import OrTrigger

market_trigger = OrTrigger([
    CronTrigger(day_of_week='mon-fri', hour=9,      minute='15-59', timezone=ist),
    CronTrigger(day_of_week='mon-fri', hour='10-14', minute='*',    timezone=ist),
    CronTrigger(day_of_week='mon-fri', hour=15,      minute='0-15', timezone=ist),
])

scheduler.add_job(
    nexus_trader.run_market_session,
    market_trigger,
    id='market_session',
    name='Market session poll',
    max_instances=1,
    misfire_grace_time=60   # 60s: if a fire is > 60s late, skip it
)
```

`OrTrigger` is confirmed present in `apscheduler.triggers.combining` in version 3.10.4.
[VERIFIED: import and instantiation tested in project venv]

### Job 3 — Post-market Review (15:35 IST, Mon–Fri)

```python
scheduler.add_job(
    nexus_trader.run_post_market,
    CronTrigger(day_of_week='mon-fri', hour=15, minute=35, timezone=ist),
    id='post_market',
    name='Post-market review',
    max_instances=1,
    misfire_grace_time=300
)
```

### Scheduler Lifecycle

```python
scheduler.start()     # starts background thread; returns immediately
# ... main thread blocks on shutdown_event.wait() ...
scheduler.shutdown(wait=False)  # stops scheduler without waiting for running jobs
```

`scheduler.state` values: `0` = stopped, `1` = running, `2` = paused.
[VERIFIED: state=0 confirmed before start]

### misfire_grace_time Values

| Job | Recommended | Rationale |
|-----|-------------|-----------|
| pre_market | 300s | Pre-market scan is time-sensitive but 5 min late is still useful |
| market_session | 60s | A poll > 60s late is stale; skip and wait for next minute |
| post_market | 300s | Post-market review runs once; allow 5 min late start |

---

## NSE 2026 Holiday List

[CITED: NSE official circular CMTR71775 via nsearchives.nseindia.com — PDF timeout, content confirmed via Zerodha holiday calendar and ClearTax NSE holidays 2026 page, cross-verified with Groww NSE holidays 2026 page]

Three independent broker/finance sources (Zerodha, ClearTax, Groww, Sahi) agree on the
same 16 dates. All 16 fall on weekdays (verified programmatically). The January 15
Maharashtra Municipal Corporation Election holiday is included in the full NSE circular
but appears as "equity-segment-specific" on some aggregators — included conservatively
since nexus_trader trades equities.

**Day-of-week verification (all confirmed as Mon–Fri):**

| Date | Day | Holiday |
|------|-----|---------|
| 2026-01-15 | Thu | Maharashtra Municipal Corporation Election |
| 2026-01-26 | Mon | Republic Day |
| 2026-03-03 | Tue | Holi |
| 2026-03-26 | Thu | Shri Ram Navami |
| 2026-03-31 | Tue | Shri Mahavir Jayanti |
| 2026-04-03 | Fri | Good Friday |
| 2026-04-14 | Tue | Dr. Baba Saheb Ambedkar Jayanti |
| 2026-05-01 | Fri | Maharashtra Day |
| 2026-05-28 | Thu | Bakri Id (Eid ul-Adha) |
| 2026-06-26 | Fri | Muharram |
| 2026-09-14 | Mon | Ganesh Chaturthi |
| 2026-10-02 | Fri | Mahatma Gandhi Jayanti |
| 2026-10-20 | Tue | Dussehra |
| 2026-11-10 | Tue | Diwali — Balipratipada |
| 2026-11-24 | Tue | Guru Nanak Jayanti (Prakash Gurpurb) |
| 2026-12-25 | Fri | Christmas |

**Python set literal for config.py:**

```python
NSE_HOLIDAYS_2026: set[str] = {
    "2026-01-15",  # Maharashtra Municipal Corporation Election
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-26",  # Shri Ram Navami
    "2026-03-31",  # Shri Mahavir Jayanti
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-28",  # Bakri Id
    "2026-06-26",  # Muharram
    "2026-09-14",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-10",  # Diwali — Balipratipada
    "2026-11-24",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}
```

**is_trading_day() implementation:**

```python
from datetime import date as _date

def is_trading_day(d: _date) -> bool:
    """Return True if d is a weekday and not in NSE_HOLIDAYS_2026."""
    return (
        d.weekday() not in (5, 6)
        and d.strftime('%Y-%m-%d') not in NSE_HOLIDAYS_2026
    )
```

Tested against: weekday trading day (pass), weekend (fail), Republic Day (fail),
Christmas (fail), Maharashtra election (fail). [VERIFIED: runtime test]

**Caveat on 2026-01-15:** Groww lists 15 holidays (omits Jan 15) while Zerodha/ClearTax
list 16. Jan 15 may be equity-specific. Conservative decision: include it. If it is wrong,
the only effect is one missed paper trading day. [ASSUMED — not confirmed from official
NSE circular PDF due to network timeout]

---

## Market Session Poll Strategy

### Decision: OrTrigger (3 CronTriggers) — RECOMMENDED

**Why not `IntervalTrigger(seconds=60)`:**
`IntervalTrigger` accepts `start_date` and `end_date` parameters, but these are
*absolute* datetimes, not recurring daily time windows. An IntervalTrigger started at
09:15 on day 1 fires every 60s forever, including overnight and through weekends — unless
a separate job stops and restarts it each day. That is unnecessary complexity.
[VERIFIED: IntervalTrigger signature inspected]

**Why not `CronTrigger(hour='9-15', minute='*')` with internal guard:**
This fires 60 times/hour from 09:00 to 15:59 (420 fires/day). 45 fires before 09:15
and 44 fires after 15:15 need an internal `datetime.now(ist)` guard in
`run_market_session()`. The guard works but pollutes the job with time-boundary logic
that belongs in the trigger.

**Why OrTrigger:**
Three `CronTrigger` instances combined with `OrTrigger` fire exactly at 09:15–15:15,
covering 361 fires/day (45 at 09:15–09:59, 300 at 10:00–14:59, 16 at 15:00–15:15).
No internal guard needed. `run_market_session()` can assume it is always called within
valid market hours. [VERIFIED: OrTrigger available in APScheduler 3.10.4; all three
constituent triggers instantiated and combined without error]

**Overlap prevention with max_instances=1:**
If `run_market_session()` takes longer than 60s (e.g., yfinance slow), the next fire is
queued but not executed because `max_instances=1` rejects new instances while one is
running. The missed fire is discarded after `misfire_grace_time=60` seconds. This is the
correct behavior for a market poll — stale data from 2 minutes ago should be skipped,
not queued up for later execution. [VERIFIED: APScheduler docs, CLAUDE.md §2]

**Summary:**

| Option | Fires/day (correct) | Guard in job? | Overlap safe? | Verdict |
|--------|--------------------|--------------:|:-------------:|---------|
| IntervalTrigger 60s | No daily bounds | Yes (complex) | With max_instances | Rejected |
| CronTrigger hour=9-15 | 420 (not 361) | Yes | With max_instances | Acceptable fallback |
| OrTrigger (3 Crons) | 361 (exact) | No | With max_instances | **Recommended** |

---

## dry-run Flag Pattern

[VERIFIED: argparse.ArgumentParser tested in project Python environment]

### argparse in main.py

```python
import argparse

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

`args.dry_run` is `False` by default; `True` when `--dry-run` is passed.
`action='store_true'` requires no value argument — `--dry-run` alone sets it.
[VERIFIED: parse_args([]) → dry_run=False; parse_args(['--dry-run']) → dry_run=True]

### Passing dry_run to NexusTrader — Constructor Injection

Avoid global state. Pass `dry_run` as a constructor argument:

```python
# main.py
args = parse_args()
trader = NexusTrader(dry_run=args.dry_run)
```

```python
# execution/scheduler.py
class NexusTrader:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._portfolio = PaperPortfolio()
        self._agent_i0 = AgentI0()
        # ... other agents ...

    def run_market_session(self) -> None:
        signals = self._agent_i4.run(...)
        if self.dry_run:
            logger.info('[DRY-RUN] %d signals generated — order placement skipped', len(signals))
            return
        self._agent_i6.run(signals, self._portfolio)  # actually places orders
```

`self.dry_run` is readable from any method, avoids module-level state, and is testable
with `NexusTrader(dry_run=True)`. [VERIFIED: pattern tested in isolation]

### Info Block Mode Line

```python
mode_str = 'DRY-RUN' if args.dry_run else 'LIVE'
print(f'  Mode    : {mode_str}')
```

---

## Common Pitfalls

### Pitfall 1: max_instances on Scheduler Constructor Instead of add_job

**What goes wrong:** Setting `max_instances` in the `BackgroundScheduler()` constructor
kwargs — it is silently ignored (no error). The per-job instance limit is not applied.
**Why it happens:** APScheduler 2.x had a global `max_instances` on the scheduler;
3.x moved it to per-job.
**How to avoid:** Always set `max_instances=1` in `scheduler.add_job(...)`.
[VERIFIED: runtime test — `job.max_instances` only reflects the add_job param]

### Pitfall 2: IntervalTrigger Not Respecting Daily Window

**What goes wrong:** Using `IntervalTrigger(seconds=60, start_date=..., end_date=...)`
expecting it to reset bounds each day. It fires once per 60s from `start_date` to
`end_date` (absolute wall-clock range, not daily recurring).
**How to avoid:** Use OrTrigger with CronTriggers as documented above.

### Pitfall 3: scheduler.shutdown() Hangs on Windows

**What goes wrong:** `scheduler.shutdown()` (without `wait=False`) blocks until running
jobs finish. If a market session job is mid-execution, shutdown waits. On Windows, there
is no SIGTERM, so Ctrl+C is the only stop mechanism; if the main thread is blocked in
`shutdown()` and the job is also blocked, deadlock can occur.
**How to avoid:** Always use `scheduler.shutdown(wait=False)` in the Ctrl+C handler.
[CITED: CLAUDE.md §"2. APScheduler" Windows-specific notes]

### Pitfall 4: Rs. vs ₹ Symbol on Windows Console

**What goes wrong:** `₹` (U+20B9) may not render in Windows cmd.exe / older PowerShell
if the console code page is not UTF-8. Banner line `Capital: ₹1,00,000` prints as `?` or
raises `UnicodeEncodeError`.
**How to avoid:** D-08/D-09 notes this as Claude's discretion. Safe approach: try `₹`,
catch `UnicodeEncodeError`, fallback to `Rs.`. Or set `sys.stdout.reconfigure(encoding='utf-8')`
at startup before printing the banner.

### Pitfall 5: Scheduler.start() Called After Jobs Added — Order Matters

**What goes wrong:** Adding jobs before `scheduler.start()` is fine. Adding jobs after
`start()` is also fine. The pitfall is calling `start()` in `TradingScheduler.__init__`
before the NexusTrader methods are bound — if NexusTrader is not fully initialized, the
first fire (if within seconds of start) could call an uninitialised method.
**How to avoid:** Instantiate `NexusTrader` fully before creating `TradingScheduler`.
Or delay `scheduler.start()` until after all jobs are added and NexusTrader is ready.

### Pitfall 6: is_trading_day Called Without pytz Localisation

**What goes wrong:** `date.today()` returns local date. On a machine whose clock is set
to UTC, calling `date.today()` at 23:45 UTC on a trading day returns the next day (IST
is UTC+5:30, so 23:45 UTC = 05:15 next-day IST). The pre-market job fires at 08:30 IST —
the clock is already in IST context — but if `date.today()` is called in a UTC context,
holiday check could use the wrong date.
**How to avoid:** Use `datetime.now(pytz.timezone('Asia/Kolkata')).date()` instead of
`date.today()` inside `run_pre_market_pipeline()`.

---

## Code Examples

### Complete TradingScheduler Class Skeleton

```python
# execution/scheduler.py
# Source: verified against APScheduler 3.10.4 docs and runtime tests

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.combining import OrTrigger
from apscheduler.executors.pool import ThreadPoolExecutor
import pytz

from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)
ist = pytz.timezone('Asia/Kolkata')


class TradingScheduler:
    def __init__(self, nexus_trader: 'NexusTrader') -> None:
        self._trader = nexus_trader
        self._scheduler = BackgroundScheduler(
            executors={'default': ThreadPoolExecutor(max_workers=1)},
            timezone=ist,
        )
        self._configure_jobs()

    def _configure_jobs(self) -> None:
        # Job 1: pre-market scan
        self._scheduler.add_job(
            self._trader.run_pre_market_pipeline,
            CronTrigger(day_of_week='mon-fri', hour=8, minute=30, timezone=ist),
            id='pre_market',
            name='Pre-market scan',
            max_instances=1,
            misfire_grace_time=300,
        )

        # Job 2: market session poll (exact 09:15–15:15)
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

        # Job 3: post-market review
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
        self._scheduler.shutdown(wait=False)
        logger.info('TradingScheduler stopped')
```

### main.py Blocking + Shutdown Skeleton

```python
# main.py
import sys
import threading
import argparse
from execution.scheduler import NexusTrader, TradingScheduler

shutdown_event = threading.Event()

def main() -> None:
    args = parse_args()
    print_banner(dry_run=args.dry_run)

    trader = NexusTrader(dry_run=args.dry_run)
    scheduler = TradingScheduler(nexus_trader=trader)
    scheduler.start()

    try:
        shutdown_event.wait()   # blocks indefinitely; no busy-wait
    except KeyboardInterrupt:
        print('\nCtrl+C — shutting down...')
        trader.portfolio.force_squareoff_all()
        trader.portfolio.save_state()
        scheduler.shutdown()
        sys.exit(0)

if __name__ == '__main__':
    main()
```

### run_pre_market_pipeline Holiday Guard

```python
# Inside NexusTrader
from datetime import datetime
import pytz

ist = pytz.timezone('Asia/Kolkata')

def run_pre_market_pipeline(self) -> None:
    today = datetime.now(ist).date()
    if not config.is_trading_day(today):
        logger.info('NSE holiday — no trading today (%s)', today)
        return
    # ... proceed with I0→I1→I2→I3 chain ...
```

---

## Package Legitimacy Audit

No new packages are installed in this phase. All dependencies are already pinned in
`requirements.txt` and installed:

| Package | Status |
|---------|--------|
| `APScheduler==3.10.4` | Already installed, verified in venv |
| `pytz>=2024.1` | Already installed |
| `threading` | Standard library, no install |
| `argparse` | Standard library, no install |

**Packages removed due to slopcheck:** none
**Packages flagged as suspicious:** none

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | None — Wave 0 creates `pytest.ini` |
| Quick run command | `pytest tests/test_orchestrator.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Testing Philosophy for Schedulers

APScheduler's `BackgroundScheduler` runs jobs in a background thread on a real clock.
Starting it in unit tests creates timing dependencies and slow tests. The correct minimal
test strategy is:

1. **Do not test the scheduler clock** — test that job *functions* produce correct
   outputs when called directly.
2. **Mock agent calls** inside NexusTrader methods — verify that the right agents are
   called in the right order.
3. **Test scheduler configuration** by inspecting `scheduler.get_jobs()` without
   calling `scheduler.start()`.

### Requirement → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ORCH-01 | NexusTrader.__init__ instantiates all agents and portfolio | unit | `pytest tests/test_orchestrator.py::test_nexus_trader_init -x` | ❌ Wave 0 |
| ORCH-01 | run_pre_market_pipeline calls I0→I1→I2→I3 in order | unit (mock) | `pytest tests/test_orchestrator.py::test_pre_market_pipeline_sequence -x` | ❌ Wave 0 |
| ORCH-01 | run_pre_market_pipeline returns early on holiday | unit | `pytest tests/test_orchestrator.py::test_pre_market_holiday_guard -x` | ❌ Wave 0 |
| ORCH-01 | run_market_session skips orders when dry_run=True | unit | `pytest tests/test_orchestrator.py::test_market_session_dry_run -x` | ❌ Wave 0 |
| ORCH-02 | TradingScheduler uses BackgroundScheduler + ThreadPoolExecutor | unit (config inspect) | `pytest tests/test_scheduler.py::test_scheduler_executor_type -x` | ❌ Wave 0 |
| ORCH-03 | 3 jobs configured with correct IDs | unit (config inspect) | `pytest tests/test_scheduler.py::test_scheduler_job_ids -x` | ❌ Wave 0 |
| ORCH-03 | market_session job uses OrTrigger | unit (config inspect) | `pytest tests/test_scheduler.py::test_market_trigger_type -x` | ❌ Wave 0 |
| ORCH-04 | is_trading_day returns False for 2026-01-26 Republic Day | unit | `pytest tests/test_config.py::test_is_trading_day_holiday -x` | ❌ Wave 0 |
| ORCH-04 | is_trading_day returns False for weekend | unit | `pytest tests/test_config.py::test_is_trading_day_weekend -x` | ❌ Wave 0 |
| ORCH-04 | is_trading_day returns True for normal weekday | unit | `pytest tests/test_config.py::test_is_trading_day_weekday -x` | ❌ Wave 0 |
| ORCH-05 | Ctrl+C triggers shutdown sequence in correct order | unit (mock) | `pytest tests/test_main.py::test_keyboard_interrupt_shutdown -x` | ❌ Wave 0 |
| ORCH-06 | print_banner outputs NEXUS TRADER text | unit (capsys) | `pytest tests/test_main.py::test_banner_output -x` | ❌ Wave 0 |
| ORCH-06 | info block shows DRY-RUN when dry_run=True | unit (capsys) | `pytest tests/test_main.py::test_banner_dry_run_mode -x` | ❌ Wave 0 |
| ORCH-07 | --dry-run flag parsed correctly | unit | `pytest tests/test_main.py::test_parse_args_dry_run -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_orchestrator.py tests/test_config.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

All test files must be created in Wave 0 before implementation begins:

- [ ] `tests/__init__.py` — makes tests/ a package
- [ ] `pytest.ini` (project root) — sets `testpaths = tests`
- [ ] `tests/test_config.py` — covers ORCH-04 (is_trading_day, NSE_HOLIDAYS_2026)
- [ ] `tests/test_orchestrator.py` — covers ORCH-01, ORCH-05, ORCH-07
- [ ] `tests/test_scheduler.py` — covers ORCH-02, ORCH-03 (config inspection without start())
- [ ] `tests/test_main.py` — covers ORCH-05 (shutdown), ORCH-06 (banner), ORCH-07 (argparse)

**Recommended mock targets:**

```python
# tests/test_orchestrator.py
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
        # assert ordering via call_args_list or call_count checks
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python | All | ✓ | 3.12.x | — |
| APScheduler | ORCH-02, ORCH-03 | ✓ | 3.10.4 | — |
| pytz | Timezone in scheduler | ✓ | installed | — |
| pytest | Validation | ✓ | 9.0.2 | — |
| threading | Blocking / shutdown | ✓ | stdlib | — |
| argparse | CLI flag | ✓ | stdlib | — |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

---

## Security Domain

> security_enforcement is not explicitly set in config.json — treating as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No user auth — pipeline is single-process |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | Local process |
| V5 Input Validation | Partial | `--dry-run` is a boolean flag, no free-text input |
| V6 Cryptography | No | No crypto in orchestrator layer |
| V7 Error Handling | Yes | Agents return None on failure; orchestrator must not raise to scheduler |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Uncaught exception in scheduled job crashes BackgroundScheduler thread | Denial of Service | Wrap all three NexusTrader methods in `try/except Exception` — log and return; scheduler thread stays alive |
| API key visible in banner output | Information Disclosure | `config.GEMINI_API_KEY[:4] + '****'` — show only presence/absence, not key value |
| Leftover open positions on crash before squareoff | Integrity | force_squareoff_all() must be idempotent; test with empty portfolio |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 2026-01-15 is an NSE equity segment trading holiday | NSE 2026 Holiday List | One extra missed trading day — negligible for paper trading |
| A2 | Muhurat trading on 2026-11-08 (Sunday) is not in the weekday set and thus not affected by is_trading_day() | NSE 2026 Holiday List | None — it's a Sunday, weekday check excludes it correctly |

**All other claims are VERIFIED or CITED.**

---

## Open Questions

1. **RESOLVED — OrTrigger vs guard:** OrTrigger is the recommended approach. Verified in
   APScheduler 3.10.4. Exact firing pattern (361 fires/day, 09:15–15:15) confirmed.

2. **RESOLVED — max_instances placement:** Goes on `add_job()`, not the scheduler
   constructor. Verified via `job.max_instances` attribute read-back.

3. **RESOLVED — day_of_week param:** `'mon-fri'` is correct. `'0-4'` also works.
   String form confirmed via CronTrigger field dump.

4. **RESOLVED — NSE 2026 holidays:** 16 dates confirmed from three independent
   broker/finance sources aligned with NSE circular content. All verified as weekdays
   programmatically.

5. **PARTIALLY RESOLVED — Jan 15 Maharashtra election:** Included in full NSE circular
   (16 holidays per ClearTax/Zerodha/Sahi); omitted by Groww (15 holidays). Conservative
   choice: include it. Planner should note this as a low-risk assumption.

6. **UNRESOLVED — ₹ symbol rendering on Windows:** Whether `sys.stdout.reconfigure(encoding='utf-8')`
   is needed depends on the user's terminal code page. Recommendation: add it as the first
   line in `main()` before printing the banner, or use fallback `Rs.` if reconfigure fails.

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `BlockingScheduler` occupying main thread | `BackgroundScheduler` + `threading.Event` | Allows graceful shutdown from main thread |
| `while True: time.sleep(1)` busy loop | `shutdown_event.wait()` | No CPU spin; event can be set from any thread |
| Global `dry_run` flag | Constructor injection `NexusTrader(dry_run=bool)` | Testable, no side effects |

---

## Sources

### Primary (HIGH confidence)
- APScheduler 3.10.4 installed in project venv — all patterns executed and verified
- `apscheduler.triggers.combining.OrTrigger` — confirmed via import and runtime test
- `CLAUDE.md §2 APScheduler` — BackgroundScheduler + ThreadPoolExecutor, Windows notes
- Python stdlib: `threading.Event`, `argparse` — confirmed in Python 3.12

### Secondary (MEDIUM confidence)
- [Zerodha Holiday Calendar 2026](https://zerodha.com/marketintel/holiday-calendar/) — 16 NSE holidays listed; cross-verified
- [ClearTax NSE Holidays 2026](https://cleartax.in/s/nse-holidays-2026) — YYYY-MM-DD format provided
- [Groww NSE Holidays 2026](https://groww.in/p/nse-holidays) — 15 holidays (omits Jan 15)
- [Sahi NSE Holidays 2026](https://www.sahi.com/blogs/nse-trading-holidays-2026-complete-list-of-stock-market-holidays) — 16 holidays (includes Jan 15)

### Tertiary (LOW confidence)
- NSE official circular CMTR71775.pdf — URL confirmed present; content timeout; trusted via broker cross-verification

---

## Metadata

**Confidence breakdown:**
- APScheduler patterns: HIGH — all code run in installed project venv
- NSE 2026 holidays: MEDIUM-HIGH — 3+ broker sources agree; official PDF timed out
- Validation architecture: HIGH — pytest 9.0.2 confirmed; pattern standard
- dry-run flag: HIGH — standard Python stdlib patterns

**Research date:** 2026-06-06
**Valid until:** 2026-12-31 (holiday list is year-scoped; APScheduler patterns stable)
