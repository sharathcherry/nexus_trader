# Phase 5: Orchestrator & Scheduler - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in 05-CONTEXT.md — this log preserves the discussion.

**Date:** 2026-06-06
**Phase:** 05-orchestrator-scheduler
**Mode:** discuss
**Areas discussed:** NSE holiday detection, NO_TRADE_DAY trigger logic, main.py blocking strategy & Ctrl+C, NEXUS ASCII banner

---

## Area 1: NSE Holiday Detection

| Question | Options | Selected |
|----------|---------|----------|
| How should NSE 2026 holidays be detected? | Hardcoded list / nselib fetch / Both | Hardcoded list in config.py (Recommended) |
| Where does the holiday list live? | config.py as NSE_HOLIDAYS_2026 / separate data module | In config.py as NSE_HOLIDAYS_2026 set |

**Decision:** Static `NSE_HOLIDAYS_2026: set[str]` in `config.py`. `config.is_trading_day(date)` checks weekend + holiday. Zero network dependency.

---

## Area 2: NO_TRADE_DAY Trigger Logic

| Question | Options | Selected |
|----------|---------|----------|
| What triggers NO_TRADE_DAY? | Holiday/weekend only / Holiday + ^NSEI volume check | Holiday/weekend check only (Recommended) |

**Decision:** `not config.is_trading_day(date.today())` is the sole check. No ^NSEI fetch. Avoids yfinance 429 false positives in pre-market window.

---

## Area 3: main.py Blocking Strategy & Ctrl+C

| Question | Options | Selected |
|----------|---------|----------|
| How does main.py stay alive? | threading.Event().wait() / while True sleep loop | threading.Event().wait() — clean block (Recommended) |
| On KeyboardInterrupt, what does shutdown do? | Force-close positions + save + stop scheduler / Just save + stop | Force-close all open positions + save portfolio + stop scheduler |

**Decision:** `shutdown_event = threading.Event()` blocks main thread. KeyboardInterrupt triggers: `force_squareoff_all()` → `save_state()` → `scheduler.shutdown(wait=False)` → `sys.exit(0)`.

---

## Area 4: NEXUS ASCII Banner

| Question | Options | Selected |
|----------|---------|----------|
| Banner style? | Hand-crafted block letters / Simple box border | Hand-crafted block letters with project info below |
| Info to show? | Capital / Date+day / Mode / API key status | All four selected |

**Decision:** ASCII block letters `NEXUS TRADER` + 4-line info: capital `₹1,00,000`, date+weekday, LIVE/DRY-RUN mode, GEMINI ✓ ANTHROPIC ✓ key status.

---

## Deferred Ideas

- Telegram notification on pipeline start/stop → ALRT-01/v2
- Web dashboard for live P&L → out of scope
- Auto-restart on crash (systemd) → deployment concern
