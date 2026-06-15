# nexus_trader — Change Log (2026-06-11)

Full record of work done in this session: bug fixes (C1-C8 + N-series), the algorithm overhaul, universe expansion, the new strategy, the dashboard rebuild, and the infra/deploy changes. Commit hashes reference `origin/main`.

> Conventions: 🔴 critical · 🟠 high · 🟡 medium · ⚪ low · 🔒 security. "Algorithmic change" = anything that alters which trades fire, at what size, price, or P&L.

---

## 1. Headline outcome

The system had **never completed a real trading session** — two bugs guaranteed the intraday loop did nothing, a third left positions unmanaged. After this session:

- Intraday loop fetches data and trades correctly (C1-C8 fixed).
- P&L measurement is now **honest** (real exit slippage + correct Zerodha charges).
- Entry/exit signals are sound (ORB ordering, chase guard, real VWAP, equity sizing).
- Universe expanded **Nifty 100 → Nifty 500** (335 liquid names mapped).
- New **RELATIVE_STRENGTH** momentum strategy added.
- Dashboard rebuilt with a timestamped **activity timeline**.
- VM consolidated from **3 duplicate trading processes → 1** (was double/triple-trading one DB).

Tests: **127 passing** (from 73 baseline). Two GSD quick tasks + a 3-agent parallel sweep.

---

## 2. Commit map

| Commit | Area | Summary |
|--------|------|---------|
| `de8bd33` | fix C1/C2/C3 | `_safe_fetch` callers, intraday cache TTL split, token-refresh chain |
| `922aa04` | fix C4/C5/C6/C7 | hard exits before circuit, daily reset on all paths, restart deadlock, shutdown liquidation |
| `b090e22` | test | encode corrected C4 circuit behavior |
| `c4ed96a` | feat C8 | `get_preopen_snapshot` batch method |
| `36421a0` | feat C8 | parameterize AgentI1 scan by `price_source` |
| `d16aa8d` | feat C8 | hybrid scheduler prep / provisional / confirm jobs |
| `015e4a8`, `43930c4`, `129f6bc`, `bd951ec`, `511ac15` | fix M-series | dynamic Nifty filter, dashboard LOG_PATH, `^NSEI` key, send_alert |
| `5e2a40a`, `e9226ff` | chore | remove tests/planning/scratch/secrets-dump from public repo |
| `fbc716c` | feat dashboard | activity timeline + dark-theme polish |
| `55ff84d` | fix H7/H8 | honest fills + centralized slippage + correct brokerage |
| `9bf41a0` | feat | Nifty 500 universe + batched pre-open scan |
| `e60e395` | feat | RELATIVE_STRENGTH strategy |
| `435636b`, `9894969` | merge | dashboard + algo worktree branches |
| `b6e68b2` | fix N-H2/N-H3 | one-shot session guard + DB connection-leak guard |

---

## 3. Critical bug fixes (C1-C8)

### C1 — `_safe_fetch()` signature mismatch *(🔴 algorithmic — loop was a no-op)*
Three callers used the old yfinance-style kwargs (`period=`, `interval=`) against the new `_safe_fetch(symbol, is_intraday, period_days)` signature → `TypeError` every call → empty DataFrame for every symbol every cycle → **no entries, no exits**.
**Fix:** `agent_i4.py` batch fetch → `is_intraday=True`; Nifty filter + scheduler briefing → `is_intraday=False, period_days=2`.

### C2 — Upstox token refresh triple-broken *(🔴 data quality)*
`scheduler.py` used `os`/`subprocess` without importing them (daily `NameError`), spawned system `python3` not the venv, and the venv lacked `undetected-chromedriver`/`pyotp`/`selenium`. Result: static token expires daily → permanent fallback to **15-min-delayed** yfinance.
**Fix:** add imports, use `sys.executable`, Telegram alert on failure. Deps installed on VM + 2 GB swap added (headless Chrome OOM guard).

### C3 — Cache TTL (300 s) vs 60 s poll → false circuit *(🔴 algorithmic)*
5-min cache returned byte-identical candles across 3 polls → `POSSIBLE_CIRCUIT` fired for every open position within ~3 min.
**Fix:** split TTL — 45 s for intraday entries, 300 s for daily.

### C4 — Circuit-flagged symbols permanently unmanaged *(🔴 algorithmic — capital risk)*
Circuit check ran *before* SL/target and skipped everything; membership was permanent. Positions rode unmanaged through their stop.
**Fix:** SL/target hard exits now run **before** circuit logic; circuit flag auto-recovers when price moves; circuit only skips partial-exit/trailing.

### C5 — Daily state never reset in a long-running service *(🔴 algorithmic)*
`reset` only ran in `__init__`. Day 2 of a continuous service: `force_squaredoff` stuck → 15:15 squareoff no-op → overnight positions; `daily_pnl` accumulated → 2% daily halt became permanent.
**Fix:** public `reset_daily_state_if_new_day()` called from `buy()`, `sell()`, `force_squareoff_all()`, and pre-market.

### C6 — Restart mid-session deadlock *(🔴)*
`_watchlist_ready` event only set by the 08:30 job; a later restart waited forever, blocking the post-market job too.
**Fix:** `run_market_session` sets the event after DB watchlist restore.

### C7 — Shutdown liquidated positions at fake prices *(🔴 corrupts ledger)*
Graceful shutdown called `force_squareoff_all({})` → every position filled at `entry_price` and `force_squaredoff=1` set.
**Fix:** shutdown logs open positions and leaves them in DB for restart reconciliation; no fake liquidation.

### C8 — Gap scanner measured *yesterday's move* *(🔴 algorithmic — core premise)*
At 08:30 no intraday data existed; `gap_pct` was computed from yesterday-close vs day-before-close = yesterday's daily change, not today's gap.
**Fix (hybrid, 3 scheduler jobs):**
- **08:30** `run_pre_market_prep` — bias (I0) + news prep, no final gaps.
- **09:08** `run_provisional_scan` — one batched Upstox pre-open quote call → gap = `(last_price − prev_close)/prev_close` → provisional watchlist.
- **09:15** `run_confirm_watchlist` — confirm/re-rank with first live 5-min candle; **only this job sets `_watchlist_ready`**.
- Entries still gated to 09:30. Degrades to 09:15-only if pre-open returns empty.

---

## 4. Algorithmic changes (the trading logic)

### 4.1 Honest fills — H7 *(commit `55ff84d`)*
Before: entries had 0.15% slippage; **exits filled at the raw candle close** (TARGET sold at `current_price ≥ target`, better than a limit fill; stops had none). P&L overstated ~0.2-0.4%/trade.
After:
- TARGET fills at `target × (1 − SLIPPAGE_PCT)` (limit-order simulation, never better than the limit).
- STOP fills at `min(current, stop) × (1 − SLIPPAGE_PCT)`.
- Partial exits use the same constant.
- `SLIPPAGE_PCT = 0.0015` is now a **single source of truth** in `utils/brokerage.py`, imported everywhere (kills the duplicate inline constants — L2).

### 4.2 Correct Zerodha charges — H8 *(commit `55ff84d`, `utils/brokerage.py`)*
Before: ₹20 cap on **combined** turnover; missing stamp duty + SEBI; GST base wrong.
After (per-leg, full breakdown):
```
brokerage        = min(20, 0.0003*buy_turnover) + min(20, 0.0003*sell_turnover)   # per ORDER
stt              = 0.00025 * sell_turnover                                         # sell-side
exchange_charges = 0.0000345 * turnover
sebi_charges     = 0.000001 * turnover                                             # ₹10/crore
stamp_duty       = 0.00003 * buy_turnover                                          # 0.003% buy-side
gst              = 0.18 * (brokerage + exchange_charges + sebi_charges)
total            = sum of all
```
Return dict keeps the `exchange` alias for backtester compatibility; adds `sebi`, `stamp`.

### 4.3 ORB ordering + override — H1 *(merged)*
- `_run_cycle` now applies the ORB override **before** `_check_entries` (was after → first ORB entry used the stale placeholder trigger).

### 4.4 Chase guard + fill-price R:R — H3 *(merged)*
- Reject entry if `fill_price > entry_trigger × 1.01` (scoped to price-level strategies GAP_AND_GO / ORB_BREAKOUT / RELATIVE_STRENGTH).
- Recompute R:R from the actual fill before buying.

### 4.5 Real VWAP_RECLAIM — H4 *(merged, `agent_i4.py`)*
Before: signal was `price ≥ premarket×1.001` → fired immediately at 09:30 for almost any stock (effectively random).
After: requires a genuine reclaim — price was **below** session VWAP last candle and **closes back above** it, using `Indicators.vwap()`.

### 4.6 GAP_FILL bounce confirmation — H5 *(merged — verify live)*
Intent: require reversal structure (close back above first-15-min low / VWAP) instead of buying on first touch of a falling price. **Flagged for live verification** that the commit fully covers this.

### 4.7 Equity-based position sizing — H6 *(merged, `order_manager.py`)*
Before: sized off remaining **cash** → position 5 risked ~₹200 instead of ₹1,000.
After: `total_equity = cash + Σ(open_qty × price)`; risk = `1% × total_equity`; cap = `MAX_POSITION_PCT × total_equity`. Deploys the intended capital across all positions.

### 4.8 NEW strategy: RELATIVE_STRENGTH *(commit `e60e395`)*
**Thesis:** on bullish/neutral days, the strongest gap-ups with volume confirmation continue trending — exploit Nifty 500 breadth to pick the leaders.
- **Trigger rule** (`agent_i3.py`): fires first on BULLISH/NEUTRAL when `gap_pct > 5%` AND `gap_score` top-tier (implies >5% gap with volume ≥ ~1.6× avg).
- **Levels:** entry = `p × 1.002`, SL = `entry − 1×ATR`, target = `entry + 2.5×ATR` (R:R 2.5).
- **Entry signal** (`agent_i4.py`): `price > session VWAP` AND `volume_ratio ≥ 1.5` (both required).
- **Exits** (`agent_i6.py`): partial exit at 1R, breakeven SL after partial, ATR trailing — same risk discipline as GAP_AND_GO.
- Obeys all global risk rules (1% risk, R:R≥1.5, max 5 positions, sector cap, 09:30 gate).

### 4.9 Universe expansion *(commit `9bf41a0`)*
- `data/universe.py`: Nifty 100 → **Nifty 500** (335 names with confirmed Upstox instrument keys; the rest fall back to yfinance). Sourced from NSE `ind_nifty500list.csv`.
- `data/upstox_keys.py`: instrument-key map regenerated to cover all 335.
- **Performance-safe flow** (B1s, 1 vCPU): ONE batched pre-open quote (≤500 keys) → shortlist top ~20 by gap → per-symbol enrichment (prev_close, ATR, volume, candles) **only on the shortlist**, never across all 500.

---

## 5. New-bug sweep (parallel investigator)

18 flagged; verified subset:
- **N-H1** (coroutine reuse) — FALSE POSITIVE (`agent_i0.run` passed as a factory).
- **N-H5** (stale `partial_exited`) — ALREADY CORRECT (uses re-fetched `_pos`).
- **N-H2** (duplicate session loop on restart) — **FIXED** (`b6e68b2`): one-shot `_session_started` guard, re-armed each trading day.
- **N-H3** (DB connection leak in `get_portfolio_summary`/`get_daily_report`) — **FIXED** (`b6e68b2`): `try/finally` close.
- **N-H4** (`partial_exit` doesn't bump `trade_count`) — WONTFIX (limit is on entries, not exits).
- Open (logged in `REMAINING_BUGS.md`): N-M1 (backtester `group_by`), N-M2 (backtester position cap), N-M3 (analytics glob never matches), N-M5 (telegram None-conn crash), N-M7 (prune uses wrong TTL), N-M8 (`date.today()` vs IST), N-L1/L3/L6.

---

## 6. Dashboard rebuild *(commit `fbc716c`)*

- **New `utils/event_timeline.py`** — parses today's `logs/nexus.log` + `logs/decisions/decisions_YYYY-MM-DD.log` + the `trades` DB table into a sorted, categorized event feed: LIFECYCLE / SCAN / TRADE / RISK / REVIEW, each with icon + color. Resilient (missing file → empty list).
- **`dashboard.py`** — new **Activity Timeline** card (scrollable) between KPIs and positions; stable KPI element IDs for targeted JS updates; redesigned dark theme.
- **`server.py`** — `/api/live-html` payload now includes `timeline_html`; 5 s auto-refresh updates the timeline in-place preserving scroll.

Lets you read the day as a story: "08:00 token refresh started → 08:30 pre-market started → 09:08 N candidates → 09:15 watchlist confirmed → 09:31 BUY … → 15:15 squareoff → 15:35 review PROFITABLE".

---

## 7. Repo hygiene & infra

- **Removed from public repo** (`5e2a40a`, `e9226ff`): `tests/`, `pytest.ini`, `.planning/`, `BUGS.md`, `scratch/` (incl. a secret-bearing script), Upstox login-flow dumps, runtime DBs, fuse temp files. `.gitignore` extended to keep them out.
- **VM (`nexus-trader-vm`, Central India):**
  - 2 GB swap added + persisted in `/etc/fstab` (Chrome OOM guard for token refresh).
  - Upstox refresh deps installed in venv.
  - **Critical fix:** removed duplicate systemd units — `nexus-trader`/`nexus-dashboard` (hyphen) were running alongside `nexus_trader`/`nexus_dashboard` (underscore), producing **3 trading processes on one SQLite DB**. Disabled the hyphen set; now exactly one trader + one dashboard, systemd-managed, dashboard HTTP 200.

---

## 8. Still open / verify

**Verify on first live session:**
- H2 (ORB recompute SL/target + R:R re-validate) and H5 (GAP_FILL bounce confirm) — confirm the commits fully cover these; reopen if a 09:15 ORB entry uses stale levels or GAP_FILL fires on first touch.
- A1 caveat — confirm Upstox `last_price` carries the pre-open IEP during the real 09:00-09:08 window (code degrades to 09:15-only if not).

**Highest-priority untouched:**
- 🔒 **S3** — leaked Upstox secrets remain in git history (`e3f5d91` on public GitHub). **Rotate client secret, TOTP secret, PIN, token now.**
- 🔒 **S1/S2** — dashboard (8080) and SSH (22) open to the world on the NSG. Restrict to your IP.
- 🟡 M-series + N-M/N-L items in `REMAINING_BUGS.md`.

---

*Generated 2026-06-11. Full open-item detail in `REMAINING_BUGS.md`; original audit in `BUGS.md`.*
