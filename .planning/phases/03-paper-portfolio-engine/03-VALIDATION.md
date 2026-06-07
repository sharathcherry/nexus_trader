---
phase: 3
slug: paper-portfolio-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-06
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | tests/conftest.py (extended from Phase 2 Wave 0) |
| **Quick run command** | `pytest tests/test_portfolio_engine.py -x -q` |
| **Full suite command** | `pytest tests/test_portfolio_engine.py -v` |
| **Estimated runtime** | ~10 seconds (all offline — SQLite in-memory or temp file) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_portfolio_engine.py -x -q`
- **After every plan wave:** Run `pytest tests/test_portfolio_engine.py -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-00-01 | 00 | 0 | PORT-01 | — | SQLite schema creates cleanly, WAL mode set | unit | `pytest tests/test_portfolio_engine.py::test_schema_creates -x -q` | ❌ W0 | ⬜ pending |
| 03-01-01 | 01 | 1 | PORT-02 | — | buy() returns True on valid trade, inserts position row | unit | `pytest tests/test_portfolio_engine.py::test_buy_success -x -q` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | PORT-03 | — | sell() returns True, closes position, records trade row | unit | `pytest tests/test_portfolio_engine.py::test_sell_records_trade -x -q` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | PORT-04 | — | brokerage math matches manual calc to within ₹0.01 | unit | `pytest tests/test_portfolio_engine.py::test_brokerage_math -x -q` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | PORT-05 | — | partial_exit() closes half qty, sets partial_exited=1 | unit | `pytest tests/test_portfolio_engine.py::test_partial_exit -x -q` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | PORT-06 | — | 6th buy rejected when 5 positions open | unit | `pytest tests/test_portfolio_engine.py::test_max_positions_rejected -x -q` | ❌ W0 | ⬜ pending |
| 03-01-06 | 01 | 1 | PORT-07 | — | is_halted=True after daily_pnl < -2% capital | unit | `pytest tests/test_portfolio_engine.py::test_halt_on_daily_loss -x -q` | ❌ W0 | ⬜ pending |
| 03-01-07 | 01 | 1 | PORT-08 | — | buy() rejected when is_halted=True | unit | `pytest tests/test_portfolio_engine.py::test_buy_rejected_when_halted -x -q` | ❌ W0 | ⬜ pending |
| 03-01-08 | 01 | 1 | PORT-09 | — | Position survives PaperPortfolio re-init (SQLite persistence) | unit | `pytest tests/test_portfolio_engine.py::test_state_survives_restart -x -q` | ❌ W0 | ⬜ pending |
| 03-01-09 | 01 | 1 | PORT-10 | — | daily_pnl resets on new trading day | unit | `pytest tests/test_portfolio_engine.py::test_daily_reset -x -q` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | PORT-11 | — | calculate_quantity returns int > 0 for valid inputs | unit | `pytest tests/test_portfolio_engine.py::test_calculate_quantity -x -q` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | PORT-12 | — | check_and_execute_exits triggers partial exit at 1:1 R:R | unit | `pytest tests/test_portfolio_engine.py::test_partial_exit_at_rr -x -q` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | PORT-13 | — | force_squareoff_all() is idempotent (second call no-ops) | unit | `pytest tests/test_portfolio_engine.py::test_force_squareoff_idempotent -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_portfolio_engine.py` — stub tests for PORT-01 through PORT-13 (all RED initially)
- [ ] `tests/conftest.py` — extend with `tmp_db_path` fixture (temporary SQLite file for isolation)

*pytest is already in requirements.txt from Phase 1.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Colored terminal output for BUY/SELL events | PORT-10 | Terminal color rendering not testable in pytest | Run `python -c "from execution.portfolio import PaperPortfolio; p=PaperPortfolio(':memory:'); ..."` and check green/red log output |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
