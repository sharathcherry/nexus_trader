---
phase: 06-dry-run-backtest
plan: 03
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 6-03 — backtest.py CLI + README.md

## Outcome
`backtest.py` at project root and `README.md` created.

## Key Details

### backtest.py
- `--start` / `--end` required args; `--capital` optional (default: config.CAPITAL)
- `validate_dates()`: `datetime.strptime(x, '%Y-%m-%d')`; `sys.exit(1)` on bad input or start > end
- Two tabulate tables with `tablefmt='rounded_outline'`: summary (7 rows) + monthly returns
- JSON saved to `logs/backtest/backtest_YYYYMMDD_HHmmss.json` — includes `trading_days_processed`
- No TradingScheduler, NexusTrader, or APScheduler imports

### README.md
- 5 sections: Overview, Prerequisites, .env Setup, Run Modes, Project Structure
- All 4 env keys with source URLs (aistudio.google.com, console.anthropic.com, BotFather, @userinfobot)
- 3 run modes: `python main.py`, `python main.py --dry-run`, `python backtest.py --start ... --end ...`
- References `google-genai` (not deprecated `google-generativeai`)
- Under 150 lines
