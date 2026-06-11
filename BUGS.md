# nexus_trader — Bug Hunt Report

**Date:** 2026-06-11
**Scope:** Full codebase (agents, execution, data, utils, server) + live Azure VM (`nexus-trader-vm`, NEXUS-TRADER-RG)
**Method:** Static analysis + log forensics + live VM inspection via `az vm run-command`
**Headline:** The system has **never completed a real trading session**. Two independent critical bugs guarantee the intraday loop does nothing, and a third guarantees positions become unmanaged even if the first two are fixed.

> **Status update 2026-06-11:** C1-C7 **FIXED** via GSD quick task `260611-96a` (commits `08c1c91`, `ae4c83c`, `c0bec42`). 94 tests passing. Live tracker: `.planning/STATE.md` → "Bug Tracker". Remaining open: C8, H1-H9, M1-M9, L1-L6, S1-S3. C2 code fix complete but VM still needs `venv/bin/pip install undetected-chromedriver pyotp selenium` and the fixed code deployed.

Severity legend: 🔴 Critical (system dead or capital mismanaged) · 🟠 High (wrong trades / corrupted results) · 🟡 Medium · ⚪ Low · 🔒 Security

---

## 🔴 CRITICAL

### C1. `_safe_fetch()` signature mismatch — intraday loop fetches nothing
**Files:** `agents/agent_i4.py:78`, `agents/agent_i4.py:375`, `execution/scheduler.py:195`
**Evidence:** VM log 2026-06-10: `Nifty filter check failed (non-fatal): MarketDataFetcher._safe_fetch() got an unexpected keyword argument 'period'`. Verified live on VM — same code deployed.

`data/market_data.py:127` defines `_safe_fetch(self, symbol, is_intraday=False, period_days=60)`, but three callers still use the old yfinance-style signature:

```python
# agent_i4.py:78 — _fetch_batch, the core 60-second polling fetcher
df = fetcher._safe_fetch(sym, period="1d", interval="5m")   # TypeError every call
```

Exception caught per-symbol → empty DataFrame for **every symbol, every cycle** → no entries, no exits, no position monitoring. Today's first real session will be a silent no-op while pre-market (which uses correct signatures) builds a watchlist and Telegram looks alive.

**Fix:** `_safe_fetch(sym, is_intraday=True)` at line 78; `_safe_fetch("^NSEI", is_intraday=False, period_days=2)` at agent_i4.py:375 and scheduler.py:195 (drop the now-dead `interval` kwarg).

---

### C2. Upstox token refresh is triple-broken — permanent fallback to 15-min delayed data
**Files:** `execution/scheduler.py:74-98`, `utils/upstox_auth.py`
**Evidence:** Verified on VM: `.upstox_token` file does not exist; `undetected_chromedriver` import fails in **both** system python3 and the venv.

Three independent failures in the chain:
1. `scheduler.py:84,87` uses `os.path` and `subprocess.run` but **neither `os` nor `subprocess` is imported** → `NameError` at 08:00 IST daily, swallowed by the generic `except` and logged as "Error during Upstox token refresh".
2. Even if fixed, it spawns `["python3", upstox_script]` — the **system** interpreter, not `venv/bin/python3`.
3. Even with the right interpreter, `undetected_chromedriver`/`pyotp`/`selenium` are **not installed in either Python** on the VM (Chrome binary itself is present).

Net effect: Upstox token from `.env` is static and expires daily (~3:30 AM IST). Every session runs on yfinance fallback — **15-minute delayed prices** — making intraday entries/SL exits meaningless even when the loop works.

**Fix:** add imports; use `sys.executable` or absolute venv path; `venv/bin/pip install undetected-chromedriver pyotp selenium` on VM; alert (Telegram) when refresh fails instead of silently degrading. Consider blocking new entries entirely when running on delayed fallback data.

---

### C3. Cache TTL (300 s) vs poll interval (60 s) → false circuit on every position
**Files:** `data/market_data.py:48` (`_cache_ttl = 300`), `agents/agent_i6.py:66`

`_safe_fetch` caches intraday candles for 5 minutes. The loop polls every 60 s. Three consecutive polls inside one TTL window return **byte-identical cached data** → `_check_circuit` sees 3 identical prices → `POSSIBLE_CIRCUIT` fires for **every symbol with an open position within ~3 minutes of any fetch**.

**Fix:** intraday cache TTL must be < poll interval (e.g. 45 s), or bypass cache in the polling path.

---

### C4. Circuit-flagged symbols become permanently unmanaged — SL never checked again
**File:** `agents/agent_i6.py:117-123`

Circuit check runs **before** stop-loss/target checks, and `circuit_set` symbols skip everything. Membership is permanent (no removal logic). Combined with C3: every open position loses all exit management ~3 cycles after entry and rides unmanaged until 15:15 force squareoff. A stock crashing through SL keeps falling with no exit.

**Fix:** check SL/target **before** circuit detection; make circuit detection require genuinely stale data (e.g. unchanged across distinct fetch timestamps); auto-remove from `circuit_set` when price changes.

---

### C5. Daily state never resets in a long-running service
**File:** `execution/portfolio.py:165-190` (`_restore_state` called only from `__init__`)

`PaperPortfolio` is constructed **once at service boot** (`scheduler.py:65`). The daily reset of `daily_pnl`, `trade_count`, `is_halted`, `force_squaredoff` only happens in `_restore_state`. On day 2 of a continuously-running systemd service:
- `force_squaredoff` is still `"1"` from day 1 → 15:15 force squareoff **no-ops** → positions held overnight (violates intraday contract).
- `daily_pnl` accumulates across days → the −2% "daily" halt becomes a cumulative all-time halt; `is_halted` once set is **never cleared**.

**Fix:** call a daily-reset method from the 08:30 pre-market job (or check `last_trade_date` at the top of every buy/sell/squareoff path).

---

### C6. Restart mid-session deadlocks the whole day
**Files:** `execution/scheduler.py:67`, `agents/agent_i4.py:351-355`

`_watchlist_ready` (a `threading.Event`) is only set inside `run_pre_market_pipeline` (08:30 job). If the service restarts after 08:30 (deploy, crash, VM reboot), the event is never set. `run_market_session` restores the watchlist from DB but `AgentI4.run()` waits on the event **forever**. With `ThreadPoolExecutor(max_workers=1)`, the stuck thread also blocks the 15:35 post-market job. One mid-day restart bricks the rest of the trading day.

**Fix:** in `run_market_session`, set `self._watchlist_ready` after DB restore when within market hours.

---

### C7. Every shutdown liquidates positions at fake entry-price fills
**Files:** `main.py:113`, `execution/portfolio.py:505`

Graceful shutdown calls `force_squareoff_all({})` with no prices → fallback fills every position at `entry_price` (recorded as ~breakeven minus charges). Any deploy/restart mid-day silently flattens real positions at fictional prices **and** sets `force_squaredoff=1`, so the legitimate 15:15 squareoff is skipped if the service comes back. P&L ledger corrupted; with C5, positions can also leak overnight.

**Fix:** fetch live prices before shutdown squareoff; if unavailable, leave positions open in DB (they're paper) and reconcile on restart; never mark `force_squaredoff` from the shutdown path.

---

### C8. Gap scanner measures *yesterday's move*, not today's gap
**Files:** `data/market_data.py:193-214`, `agents/agent_i1.py:57-61`, scheduled at 08:30 IST

At 08:30 there are no intraday candles yet, so `get_premarket_price` falls back to the **last daily close** (yesterday). `get_previous_close` returns `iloc[-2]` (day before yesterday). So `gap_pct = yesterday's close vs day-before's close` = **yesterday's daily change**, not today's gap. Neither Upstox nor yfinance (with `prepost=False`) provides NSE pre-open (09:00-09:08) prices. The entire "gap" premise of the watchlist is computed from stale data every single day.

**Fix options:** (a) move the scan to ~09:08-09:12 using NSE pre-open data (`nsepython`/NSE pre-open API), (b) rescan at 09:15 with the first live candle open vs prev close, or (c) accept "yesterday's movers" explicitly and rename/re-tune the strategy.

---

## 🟠 HIGH

### H1. Entries checked *before* ORB override in the same cycle
**File:** `agents/agent_i4.py:326-327` — `_run_cycle` order: `_check_entries(...)` then `_maybe_apply_orb_override(...)`. On the first cycle at/after 09:30, ORB_BREAKOUT entries are evaluated against the pre-market **placeholder** trigger (`premarket*1.005`) before the real ORB high replaces it. **Fix:** swap the order.

### H2. ORB override updates trigger but not SL/target
**Files:** `agents/agent_i4.py:125-136`, `agents/agent_i3.py:190-194`
SL stays `prev_close − 0.5·ATR`, target stays `placeholder_trigger + 2·ATR`. If ORB high > stale target, the buy can be instantly followed by `TARGET_HIT` next cycle (round-trip churn for charges). Pre-market R:R≥1.5 validation is void after override. **Fix:** recompute SL (ORB low) and target (from ORB high), re-validate R:R, skip if < 1.5.

### H3. No R:R or chase guard at fill time
**File:** `agents/agent_i4.py:232-273`
Signal is unbounded `price >= trigger`; with 60 s polls price may be far past trigger; SL/target are fixed pre-market. Decision log shows an accepted entry with **R:R 0.80** (< 1.5 min). **Fix:** reject if `current_price > trigger * 1.01` (configurable) and re-check R:R with actual fill price.

### H4. VWAP_RECLAIM never computes VWAP
**Files:** `agents/agent_i3.py:196-199`, `agents/agent_i4.py:237`
Trigger = `premarket*1.001`, signal `price >= trigger` → fires almost immediately at 09:30 for any |gap| < 2% stock. `Indicators.vwap()` exists but is never used in the entry path. This is the fallback strategy, so likely the majority of trades — effectively random longs. **Fix:** require price crossing above session VWAP (e.g. close above VWAP after trading below it).

### H5. GAP_FILL buys a falling knife with no confirmation
**Files:** `agents/agent_i3.py:184-188`, `agents/agent_i4.py:239-240`
Signal `price <= premarket*1.001` is true at open for nearly any gap-down stock → immediate entry, no reversal confirmation. **Fix:** require bounce structure (e.g. close back above first-15-min low or above VWAP).

### H6. Position sizing uses remaining cash, not equity
**File:** `execution/order_manager.py:64-72`
`portfolio.capital` is cash after deducting open-position cost. Position 1 risks 1% of ₹1,00,000; position 5 risks 1% of leftover cash (~₹200 risk, ~₹4k cap). Contradicts the documented 5×₹20k design (comment at line 54). **Fix:** size off equity = cash + Σ(open qty × entry price).

### H7. Exit fills are optimistic; slippage only on entry
**Files:** `agents/agent_i4.py:263` (entry slippage 0.15%), `agents/agent_i6.py:127,144` (exits at raw candle close)
TARGET_HIT sells at `current_price ≥ target` (better than a limit fill); SL fills get no adverse slippage. Paper results systematically overstated ~0.2-0.4%/trade — fatal for evaluating an intraday edge. **Fix:** fill targets at `target`, stops at `min(current, stop)·(1−slippage)`, apply exit slippage symmetric to entry.

### H8. Brokerage model undercharges
**File:** `utils/brokerage.py`
- Zerodha caps ₹20 **per order** (buy + sell ≤ ₹40); code caps ₹20 on combined turnover.
- Missing stamp duty (0.003% buy-side) and SEBI charges (₹10/crore).
- GST base should include exchange transaction charges, not brokerage alone.
**Fix:** per-leg brokerage min(20, 0.0003·leg_turnover); add stamp duty + SEBI; GST = 0.18·(brokerage + exchange_charges).

### H9. Duplicate, divergent exit engines
**File:** `execution/order_manager.py:79-156` (`check_and_execute_exits`) is dead code — the live loop uses `AgentI6.monitor_positions` only. Two copies of SL/target/partial logic already differ (OrderManager computes partial threshold off the *trailed* SL — wrong after trailing; AgentI6 uses original watchlist SL — right). **Fix:** delete the OrderManager copy (keep `calculate_quantity`).

---

## 🟡 MEDIUM

### M1. AgentI0 bias prompt sends only absolute index closes
**File:** `agents/agent_i0.py:89-99`. Gemini receives `SP500: 6044.12` etc. with no change %. Direction cannot be inferred from levels → bias output is noise; `gift_nifty_gap_pct` is hallucinated. **Fix:** send 1-day % changes (fetch 2 closes per index — data already available).

### M2. Rule-based bias fallback is dead code
**File:** `agents/agent_i0.py:151` expects key `"^GSPC"` with a dict; `get_global_indices()` returns `"SP500"` with a float → always NEUTRAL (acknowledged in docstring but still misleading).

### M3. Module-level fetch cache never evicted
**File:** `data/market_data.py:47`. Class-level dict grows all day (100-symbol universe × variants) on a 1 GB-RAM VM with no swap. **Fix:** purge expired entries on insert, or use a bounded LRU.

### M4. Nifty bearish filter runs once at session start only
**File:** `agents/agent_i4.py:371-394`. Market can turn bearish at 11:00 — filter never re-evaluates. Also uses daily candles where today's "close" at 09:15 ≈ open (near-zero change). Low signal value as implemented.

### M5. `sell()` doesn't validate qty against position qty
**File:** `execution/portfolio.py:367-417`. Oversized qty would record a phantom profit/loss and delete the whole position. Internal callers are currently consistent, but one refactor away from corruption. **Fix:** clamp/reject `qty > position.qty`.

### M6. `Indicators.orb()` assumes df starts at 09:15
**Files:** `data/indicators.py:95-116`, called from `agent_i4.py:125` with **unfiltered** `_safe_fetch` output (Upstox intraday can include pre-open candles). `df.head(3)` may then span pre-open. **Fix:** session-filter (≥ 09:15) before ORB computation (reuse `get_intraday_candles` logic).

### M7. dashboard `server.py` polls yfinance every 10 s
**File:** `server.py:36-75`. `yf.download` every 10 s from the same VM IP risks HTTP 429 rate-limiting that also degrades the trading process's yfinance fallback. **Fix:** ≥ 60 s interval, reuse main fetcher cache, or read prices from the trading process.

### M8. Local Windows DB polluted by tests
**File (local only):** `execution/portfolio.db` — ghost WIPRO.NS position from 2026-06-06 21:10 (market closed), capital ₹94,000. Tests write to the production DB path. VM DB is clean. **Fix:** point tests at a temp DB (conftest fixture); delete local DB before any local live run.

### M9. SL exit logs `net_pnl = gross_pnl`
**File:** `agents/agent_i6.py:134,151` — decision-log analytics overstate net on every hard exit (brokerage=0). Ledger itself is correct; analytics diverge.

---

## ⚪ LOW

- **L1.** `agent_i4.py:48` — `AgentI4.run(watchlist, ...)` parameter is ignored; `watchlist_map` comes from `__init__`. Confusing API.
- **L2.** `order_manager.py:30` — `_SLIPPAGE_PCT` defined but unused there (real one re-declared inline at `agent_i4.py:263`). Duplication drift risk.
- **L3.** `agent_i2.py` — yfinance `.news` for NSE tickers is frequently empty/irrelevant; most candidates pass as UNKNOWN, so the Gemini news filter rarely filters. Budget noise.
- **L4.** `config.py:67` — 2027 NSE holiday calendar empty (warning exists; will silently trade holidays in 2027 using 2026 fallback).
- **L5.** `portfolio.py:645-665` — `get_portfolio_summary`/`get_daily_report` use a non-context-managed connection; `conn is None` check is dead (sqlite3.connect never returns None).
- **L6.** Repo root contains `upstox_page.html`, `upstox_error.png`, `upstox_pin_error.png` — login-flow page dumps/screenshots tracked in the repo. Scrub and gitignore.

---

## 🔒 SECURITY (Azure VM)

### S1. Dashboard exposed to the entire internet, no auth
Flask binds `0.0.0.0:8080` (`server.py` last line); NSG rule `open-port-8080` allows source `*`. Anyone can browse `http://52.172.251.246:8080` — trades, capital, win rate, and 80 lines of application logs (`/` and JSON API). Log lines can leak symbols, errors, file paths.
**Fix:** restrict NSG source to your IP, or add basic auth / bind to localhost + SSH tunnel.

### S2. SSH open to the world
NSG allows port 22 from `*` (two duplicate rules). Standing brute-force target.
**Fix:** restrict source IP, or use Azure Bastion / JIT access.

### S3. High-value secrets in `.env` on the VM
`UPSTOX_PIN`, `UPSTOX_TOTP_SECRET`, `UPSTOX_CLIENT_SECRET` together allow full broker-account login automation. Combined with S1/S2 exposure, treat the VM as a high-value target. Ensure `.env` is mode 600, owned by `azureuser`, and never served by the dashboard.

---

## Infra notes (not bugs, but will bite)

- **B1s VM, 844 MB RAM, no swap.** Headless Chrome for the Upstox login (C2 fix) typically needs 300-500 MB — likely OOM during token refresh while the trading process runs. Add a 1-2 GB swap file or upgrade to B2s before enabling Selenium refresh.
- **VM repo has no readable git state** via run-command (root ownership warning) — no confirmed sync mechanism between local repo and VM. Risk of divergent fixes. Establish `git pull` deploy flow.
- `nexus.log.2026-06-09` and most log history are test-run artifacts; don't mistake them for live sessions when evaluating performance.

---

## Recommended fix order

| # | Bug | Why first |
|---|-----|-----------|
| 1 | C1 signature mismatch | Without it, nothing else is even reachable |
| 2 | C5 daily reset + C6 restart deadlock + C7 shutdown liquidation | Service-lifetime correctness; any restart corrupts the day |
| 3 | C3 cache TTL + C4 circuit ordering | Otherwise every position goes unmanaged within minutes |
| 4 | C2 token refresh chain | Real-time data; without it all fills are 15-min stale |
| 5 | H7/H8 honest fills + charges | Make paper results trustworthy before judging strategy |
| 6 | H1/H2/H3 ORB + chase guards | Stop structurally bad entries |
| 7 | C8 gap timing, H4/H5 strategy logic | The actual edge — only worth tuning once measurement is honest |
| 8 | S1/S2 NSG lockdown | 5 minutes in the Azure portal; do it today |

**Bottom line:** fix items 1-4 and the system will, for the first time, actually trade a session. Fix item 5 before believing any P&L it produces.
