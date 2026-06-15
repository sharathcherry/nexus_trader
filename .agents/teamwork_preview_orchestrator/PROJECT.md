# Project: Nexus Trader Health Audit and Bug Fixes

## Architecture
- Nexus Trader algorithmic trading bot runs a 3-stage pipeline (Pre-market scan -> Provisional watchlist -> Confirm + execute).
- The pipeline execution and trade decisions are logged in `logs/nexus.log` (and rotated files) and daily decision logs in `logs/decisions/`.
- Codebase consists of directories:
  - `agents/`: Core trading bot and pipelined stages.
  - `execution/`: Portfolio management and order execution.
  - `data/`: Data loading/saving.
  - `utils/`: Analytics logging, Telegram notification, and common utils.

## Milestones
| # | Name | Scope | Dependencies | Status | Agent/Conv ID |
|---|------|-------|-------------|--------|---------------|
| 1 | Exploration & Audit | Deeply parse all log files, audit pipeline stages (R1), audit trade decisions (R2), verify analytics and Telegram settings (R3), propose fixes. | None | DONE | a7a0b31b-c2d5-43ab-91d7-32cdbbb15bca |
| 2 | Implementation & Fixes | Apply targeted minimal fixes to source code files (R4), commit fixes, verify that pytest passes, and produce final summary. | M1 | DONE | f9c30b51-ec05-4d9e-935e-81017181ee10 |

## Code Layout
- `agents/`
- `execution/`
- `data/`
- `utils/`
- `logs/` (logs directory)
- `tests/` (unit and integration tests)
