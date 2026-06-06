---
phase: "05"
slug: "orchestrator-scheduler"
date: "2026-06-06"
---

# Phase 5: Orchestrator & Scheduler - Validation Strategy

## Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pytest.ini` (project root) — sets `testpaths = tests` |
| Quick run command | `pytest tests/test_orchestrator.py tests/test_config.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

## Testing Philosophy

APScheduler's `BackgroundScheduler` runs jobs in a background thread on a real clock. Do NOT test the scheduler clock. Instead:
1. Test job *functions* directly (call NexusTrader methods without starting scheduler)
2. Mock agent calls inside NexusTrader methods — verify correct agents called in correct order
3. Test scheduler *configuration* by inspecting `scheduler.get_jobs()` without calling `scheduler.start()`

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ORCH-01 | NexusTrader.__init__ instantiates all agents and portfolio | unit | `pytest tests/test_orchestrator.py::test_nexus_trader_init -x` | No — Wave 0 |
| ORCH-01 | run_pre_market_pipeline calls I0→I1→I2→I3 in order | unit (mock) | `pytest tests/test_orchestrator.py::test_pre_market_pipeline_sequence -x` | No — Wave 0 |
| ORCH-01 | run_pre_market_pipeline returns early on holiday | unit | `pytest tests/test_orchestrator.py::test_pre_market_holiday_guard -x` | No — Wave 0 |
| ORCH-01 | run_market_session skips orders when dry_run=True | unit | `pytest tests/test_orchestrator.py::test_market_session_dry_run -x` | No — Wave 0 |
| ORCH-02 | TradingScheduler uses BackgroundScheduler + ThreadPoolExecutor | unit (config inspect) | `pytest tests/test_scheduler.py::test_scheduler_executor_type -x` | No — Wave 0 |
| ORCH-03 | 3 jobs configured with correct IDs | unit (config inspect) | `pytest tests/test_scheduler.py::test_scheduler_job_ids -x` | No — Wave 0 |
| ORCH-03 | market_session job uses OrTrigger | unit (config inspect) | `pytest tests/test_scheduler.py::test_market_trigger_type -x` | No — Wave 0 |
| ORCH-04 | is_trading_day returns False for 2026-01-26 Republic Day | unit | `pytest tests/test_config.py::test_is_trading_day_holiday -x` | No — Wave 0 |
| ORCH-04 | is_trading_day returns False for weekend | unit | `pytest tests/test_config.py::test_is_trading_day_weekend -x` | No — Wave 0 |
| ORCH-04 | is_trading_day returns True for normal weekday | unit | `pytest tests/test_config.py::test_is_trading_day_weekday -x` | No — Wave 0 |
| ORCH-05 | Ctrl+C triggers shutdown sequence in correct order | unit (mock) | `pytest tests/test_main.py::test_keyboard_interrupt_shutdown -x` | No — Wave 0 |
| ORCH-06 | print_banner outputs NEXUS TRADER text | unit (capsys) | `pytest tests/test_main.py::test_banner_output -x` | No — Wave 0 |
| ORCH-06 | info block shows DRY-RUN when dry_run=True | unit (capsys) | `pytest tests/test_main.py::test_banner_dry_run_mode -x` | No — Wave 0 |
| ORCH-07 | --dry-run flag parsed correctly | unit | `pytest tests/test_main.py::test_parse_args_dry_run -x` | No — Wave 0 |

## Sampling Rate

- **Per task commit:** `pytest tests/test_orchestrator.py tests/test_config.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

## Wave 0 Gaps

All test files must be created before implementation begins:

- [ ] `tests/__init__.py` — makes tests/ a package (may already exist from Phase 4C)
- [ ] `pytest.ini` (project root) — sets `testpaths = tests` (may already exist)
- [ ] `tests/conftest.py` — shared fixtures: mock agents, mock portfolio
- [ ] `tests/test_config.py` — covers ORCH-04 (is_trading_day, NSE_HOLIDAYS_2026)
- [ ] `tests/test_orchestrator.py` — covers ORCH-01, ORCH-05, ORCH-07
- [ ] `tests/test_scheduler.py` — covers ORCH-02, ORCH-03 (config inspection without start())
- [ ] `tests/test_main.py` — covers ORCH-05 (shutdown), ORCH-06 (banner), ORCH-07 (argparse)

*Extracted from 05-RESEARCH.md § Validation Architecture — 2026-06-06*
