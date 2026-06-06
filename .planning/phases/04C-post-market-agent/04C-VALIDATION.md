---
phase: "04C"
slug: "post-market-agent"
date: "2026-06-06"
---

# Phase 4C: Post-Market Agent - Validation Strategy

## Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none — see Wave 0 gaps below |
| Quick run command | `pytest tests/test_agent_i9.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGNT-13 | Prompt built from trade ledger + 20-day stats; stream called; token count logged | unit (mock anthropic client) | `pytest tests/test_agent_i9.py::test_prompt_construction -x` | No — Wave 0 |
| AGNT-13 | Token cap truncation drops oldest days then time fields | unit | `pytest tests/test_agent_i9.py::test_token_cap_truncation -x` | No — Wave 0 |
| AGNT-14 | Valid JSON response parses into DailyReview | unit | `pytest tests/test_agent_i9.py::test_parse_valid_response -x` | No — Wave 0 |
| AGNT-14 | Partial/invalid JSON written to review_partial file | unit | `pytest tests/test_agent_i9.py::test_partial_response_saved -x` | No — Wave 0 |
| AGNT-15 | MAX_OPEN_POSITIONS raise rejected | unit | `pytest tests/test_agent_i9.py::test_reject_max_positions -x` | No — Wave 0 |
| AGNT-15 | MIN_RISK_REWARD below 1.5 rejected | unit | `pytest tests/test_agent_i9.py::test_reject_min_rr -x` | No — Wave 0 |
| AGNT-15 | RISK_PER_TRADE_PCT above 1.5% rejected | unit | `pytest tests/test_agent_i9.py::test_reject_risk_pct -x` | No — Wave 0 |
| AGNT-16 | review_YYYYMMDD.json written on success | unit | `pytest tests/test_agent_i9.py::test_output_file_success -x` | No — Wave 0 |
| AGNT-16 | review_failed_YYYYMMDD.json written on API exception | unit | `pytest tests/test_agent_i9.py::test_output_file_failure -x` | No — Wave 0 |
| AGNT-16 | Tabulate summary prints in all three states | unit | `pytest tests/test_agent_i9.py::test_terminal_summary -x` | No — Wave 0 |

## Sampling Rate

- **Per task commit:** `pytest tests/test_agent_i9.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

## Wave 0 Gaps

- [ ] `tests/test_agent_i9.py` — covers AGNT-13 through AGNT-16
- [ ] `tests/conftest.py` — shared fixtures: mock anthropic client, in-memory SQLite with trades, tmp_path for output files
- [ ] `tests/` directory itself — does not yet exist

*Extracted from 04C-RESEARCH.md § Validation Architecture — 2026-06-06*
