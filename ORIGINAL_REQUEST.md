# Original User Request

## Initial Request — 2026-06-15T10:32:06+05:30

<USER_REQUEST>
Perform a full end-to-end health audit of the Nexus Trader algorithmic trading bot by deeply analysing all available log files. The bot runs a 3-stage pipeline (Pre-market scan → Provisional watchlist → Confirm + execute). Investigate whether each stage is operating correctly, diagnose root causes of any failures, AND automatically apply code fixes where issues are found.

Working directory: C:\Users\katuk\OneDrive\Desktop\projects\stockss
Integrity mode: development

## Log Resources

| File | Contents |
|------|----------|
| `logs/nexus.log` | Current main application log |
| `logs/nexus.log.2026-06-07` to `2026-06-10` | Historical run logs |
| `logs/decisions/decisions_2026-06-07.log` to `2026-06-11.log` | Per-day decision logs |
| `logs/analytics/` | Analytics output directory (currently empty — flag if this is a bug) |
| Source code | `agents/`, `execution/`, `data/`, `utils/` |

## Requirements

### R1. Pipeline Stage Health
Audit every stage of the 3-stage scheduler pipeline across all log dates.
For each stage (prep/pre-market, provisional watchlist, confirm/execute),
determine: Did it run? Did it complete without errors? Were outputs passed
correctly to the next stage? Report timings and any missing stage runs.

### R2. Decision Quality Audit
Parse all `decisions_*.log` files. For each trade decision:
- Were the gap%, volume filters, and Nifty bias filter applied correctly?
- Were SL/Target/R:R values calculated correctly relative to fill_price?
- Were any stocks incorrectly skipped or incorrectly included?
- Flag any decisions with suspicious data (zero prices, NaN R:R, wrong date timezone).

### R3. Data & Notification Integrity
- Verify why `logs/analytics/` is empty — determine if the AnalyticsLogger
  is being called and if it is writing correctly.
- Check whether Telegram notifications are being sent for key events
  (market open, watchlist built, fills, session end).
- Check if any log errors are recurring (e.g. yfinance 429s, SQLite locks,
  token refresh failures).

### R4. Automatic Fix Application
For every confirmed bug found in R1–R3, apply a minimal targeted code fix
directly to the relevant source file. Commit each fix with a descriptive
git commit message. Do NOT refactor working code — only fix confirmed issues.

## Acceptance Criteria

### Pipeline Coverage
- [ ] Every log date has a documented stage-by-stage execution trace
- [ ] Any date missing a stage has a confirmed root cause

### Decision Log Correctness
- [ ] All R:R values checked — flag any that are 0, NaN, or use pre-slippage price
- [ ] All Nifty filter invocations checked — flag any incorrect blocks on green days
- [ ] All timezone anomalies in decisions flagged (should be IST throughout)

### Analytics & Notifications
- [ ] Root cause confirmed for empty `logs/analytics/` directory
- [ ] Telegram send events verified in main log — flag any session with zero sends
- [ ] All recurring errors documented with frequency counts

### Code Fixes
- [ ] Each fix is a minimal, targeted change with a git commit
- [ ] No fix breaks existing passing tests (`pytest tests/`)
- [ ] A final summary lists every bug found, its root cause, and whether it was fixed or flagged for manual review
</USER_REQUEST>
