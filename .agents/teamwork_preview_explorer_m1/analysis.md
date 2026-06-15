# Nexus Trader Bot Audit Analysis Report

## Executive Summary
This read-only audit investigates the pipeline health, decision quality, and data/notification integrity of the Nexus Trader bot based on source code and historical logs (from `2026-06-06` to `2026-06-11`). 

The audit reveals that:
1. **No production scheduled session was ever executed.** The log history consists entirely of short-duration unit/integration test runs (`pytest`) and manual dry-runs.
2. A critical **race condition** exists in `execution/scheduler.py` where the market session loop can forcefully initialize with stale or empty watchlist data if the pre-market watchlist confirmation takes longer than 1 minute.
3. Decision logs contain **negative R:R ratios (-2.00)** and incorrect entry parameters because test runs dynamically log to production directories due to **test log pollution**.
4. **Hold time calculations are broken** because they use the current wall-clock system time (`datetime.now()`) rather than the trade's database-recorded exit time.
5. The `logs/analytics/` directory is empty because **session log hooks are dead code** (never called), and trade logging is mocked out during tests.
6. A compile-time **NameError** exists in `data/market_data.py` where the typing construct `Any` is used without being imported, preventing tests from running.

---

## R1: Pipeline Stage Health Audit

### 1. Stage Trace Analysis
We analyzed `logs/nexus.log` and historical files (`nexus_*.log` and `nexus.log.*`):
* **Pre-Market Prep & Scan (08:30 / 09:08 IST):** Traces of `Pre-market prep complete — bias cached for the day` and `Provisional watchlist built` appear in logs. However, all these logs are timestamps from developer manual commands or test suite runs.
* **Watchlist Confirmation (09:15 IST):** In tests, we see `Confirm watchlist pipeline failed: test_nexus_trader_pre_market_no_candidates.<locals>.fake_i1() got an unexpected keyword argument 'price_source'`. This indicates that the pre-market watchlist pipeline has crashed repeatedly in integration tests.
* **Intraday Execution (09:16 - 15:15 IST):** The live market loop (`AgentI4: watchlist ready -- starting market session loop`) is only logged during tests, running for a split second before a simulated force squareoff closes the session.

### 2. Root Cause of Missing Stages
No live market daemon was ever started. The logs are entirely developer-driven runs. There is no evidence of a persistent scheduler running continuously across trading hours (Mon-Fri, 08:00 - 15:40 IST).

### 3. Critical Scheduler Race Condition
In `execution/scheduler.py`, the `confirm_watchlist` job runs at `09:15`, and the `market_session` job runs at `09:16`. 
If `confirm_watchlist` takes more than 1 minute to complete (due to API latency, rate limits, or network lag), the `_watchlist_ready` event is still unset at `09:16`.
When `run_market_session` fires at `09:16`, it checks if the event is set:
```python
if not self._watchlist_ready.is_set():
    logger.info("Watchlist ready event not set (restart after pre-market) — setting from restored state")
    self._watchlist_ready.set()
```
Because the event is unset, it assumes a process restart occurred. It forcefully sets the event and proceeds to run `AgentI4`. However, `self._watchlist` has not been finalized yet. As a result, the live session starts with an empty watchlist or stale provisional entries, failing to wait for the confirmation process to complete.

---

## R2: Decision Quality Audit

### 1. Negative R:R Ratios
In `logs/decisions/decisions_2026-06-07.log` (and subsequent dates), we observe:
```text
[2026-06-07 08:42:27 IST] BUY_DECISION -- SYM.NS
  Strategy        : GAP_FILL
  Entry price     : Rs1450.00
  Stop loss       : Rs1430.00
  Target          : Rs1410.00
  R:R ratio       : -2.00
  Max risk        : Rs20.00
  Max reward      : Rs-40.00
```
This occurs because the test suite executes tests that manually define mock watchlists with invalid targets (target < stop loss for long trades) and triggers buys.
The production code has a guard in `agents/agent_i3.py` (lines 105-111) to reject `GAP_FILL` setups where target <= entry trigger, but the unit tests manually bypass the pre-market selection filter and pass invalid setups directly to `AgentI4`.

### 2. Stale/Unknown Market Bias
In `logs/decisions/decisions_*.log`, the `Market bias` is logged as `UNKNOWN` for all trades:
`Market bias     : UNKNOWN`
This is because tests bypass the scheduler's cached `self._bias` and run `_check_entries` directly, leaving the context bias field as a default fallback string `"UNKNOWN"`.

### 3. Incorrect Hold Times (Historical review)
In `utils/decision_logger.py` line 196:
```python
hold_mins = int((datetime.now(IST) - entry_dt).total_seconds() / 60)
```
This subtracts the trade entry time from the current system wall-clock time (`datetime.now()`). When running tests or backtests on historical logs, `datetime.now()` refers to the developer's execution time, resulting in massive, incorrect, or negative hold times. The trade's actual exit time is completely ignored.

### 4. Test Log Pollution (Severe Isolation Failure)
The test suite does not mock or redirect file logging. Whenever `pytest` runs, the real `DecisionLogger` writes directly to `logs/decisions/decisions_YYYY-MM-DD.log`, and the real root logger writes to `logs/nexus.log`. This pollutes production audit logs with garbage test records.

---

## R3: Data & Notification Integrity Audit

### 1. Why `logs/analytics/` is Empty
* **Trade logs (`trades_*.json` & `analytics.json`):** These are only written when `analytics.log_trade` is called within the real `PaperPortfolio.sell()` method. Since tests mock out the portfolio using `mock_portfolio_factory()`, the real `sell()` method is never called in the test suite. Since no live session has run, the real portfolio has never been used to execute a trade.
* **Session logs (`session_*.json`):** `log_session_start` and `log_session_end` in `utils/analytics_logger.py` are dead code. They are defined but never imported or called anywhere in the scheduler or trade loop.

### 2. Telegram Send Failures
The test environment sets placeholder credentials (`fake-token` / `fake-chat`). 
* In historical log files (`nexus.log.2026-06-08`), we see warning entries:
  `utils.telegram — Telegram send failed: 404 {"ok":false,"error_code":404,"description":"Not Found"}`
  This indicates that when credentials were non-empty but invalid, the notification engine attempted real HTTP requests and failed with a Telegram 404 response.
* In newer logs, the checks for `"fake-token"` disable the notifier completely, printing:
  `utils.telegram — TelegramNotifier: disabled (placeholder keys)`.
* Therefore, all logged execution sessions has zero successful notifications sent.

### 3. Recurring Error Frequency Table

| Error Signature | Log Date(s) | Frequency | Root Cause |
| :--- | :--- | :---: | :--- |
| `TypeError: fake_i1() got an unexpected keyword argument 'price_source'` | 2026-06-11 | 5 | In `tests/test_orchestrator.py`, the mocked `fake_i1` lacks the signature update introduced in the refactored `agent_i1.run(price_source)`. |
| `TypeError: MarketDataFetcher._safe_fetch() got an unexpected keyword argument 'period'` | 2026-06-07, 2026-06-10 | ~24 | Stale parameter name in test mock definitions calling historical data fetchers. |
| `JSON parse failed: Expecting property name...` | 2026-06-07, 2026-06-08, 2026-06-10, 2026-06-11 | ~20 | Groq AI Post-market review response returned malformed JSON blocks that failed parsing in `agent_i9.py`. |
| `_safe_fetch_yf(^NSEI): '<' not supported between instances of 'MagicMock' and 'datetime.datetime'` | 2026-06-11 | 2 | During test runs, yfinance mock output failed type comparison with datetime ranges inside `data_layer`. |
| `NameError: name 'Any' is not defined` (Blocker) | 2026-06-15 | 1 (crash) | Blocker NameError in `data/market_data.py` on `Any` typing wrapper prevents tests from loading conftest. |

---

## Recommended Code Changes

### 1. Fix compile-time `NameError` in `data/market_data.py`
Add `Any` import to prevent conftest load failures.
* **File:** `data/market_data.py`
* **Line Range:** 11-15
* **Target Content:**
```python
import os
import time
from datetime import datetime, timedelta
```
* **Replacement Content:**
```python
import os
import time
from datetime import datetime, timedelta
from typing import Any
```

### 2. Fix scheduler race condition in `execution/scheduler.py`
Add a flag tracking if the confirm watchlist job is executing, preventing the market session from setting `_watchlist_ready` forcefully.
* **File:** `execution/scheduler.py`
* **Line Range:** 70-76
* **Target Content:**
```python
        self._session_started = False  # N-H2 one-shot guard for market session
        logger.info(f"NexusTrader initialized (dry_run={dry_run})")
```
* **Replacement Content:**
```python
        self._session_started = False  # N-H2 one-shot guard for market session
        self._confirm_job_started = False  # Guard against confirm vs market session race
        logger.info(f"NexusTrader initialized (dry_run={dry_run})")
```

* **File:** `execution/scheduler.py`
* **Line Range:** 238-245
* **Target Content:**
```python
    def run_confirm_watchlist(self, date_override: date | None = None) -> None:
        """
        09:15 confirm: re-rank against the first live 5-min candle and finalize
        self._watchlist. This is the ONLY job that sets _watchlist_ready — on a
        holiday it still sets the event so AgentI4 never hangs.
        """
        today = (
```
* **Replacement Content:**
```python
    def run_confirm_watchlist(self, date_override: date | None = None) -> None:
        """
        09:15 confirm: re-rank against the first live 5-min candle and finalize
        self._watchlist. This is the ONLY job that sets _watchlist_ready — on a
        holiday it still sets the event so AgentI4 never hangs.
        """
        self._confirm_job_started = True
        today = (
```

* **File:** `execution/scheduler.py`
* **Line Range:** 346-349
* **Target Content:**
```python
        if not self._watchlist_ready.is_set():
            logger.info("Watchlist ready event not set (restart after pre-market) — setting from restored state")
            self._watchlist_ready.set()
```
* **Replacement Content:**
```python
        if not self._watchlist_ready.is_set() and not getattr(self, "_confirm_job_started", False):
            logger.info("Watchlist ready event not set (restart after pre-market) — setting from restored state")
            self._watchlist_ready.set()
```

### 3. Fix trade hold time calculation in `utils/decision_logger.py`
Accept and parse `exit_time` when calculating hold times.
* **File:** `utils/decision_logger.py`
* **Line Range:** 171-200
* **Target Content:**
```python
    def sell_decision(
        self,
        symbol: str,
        exit_reason: str,
        entry_price: float,
        exit_price: float,
        qty: int,
        gross_pnl: float,
        net_pnl: float,
        brokerage: float,
        entry_time: str,
        strategy: str,
    ) -> None:
        """Log every sell with full P&L breakdown and hold time."""
        direction = "PROFIT" if net_pnl >= 0 else "LOSS"
        try:
            try:
                entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
                entry_dt = IST.localize(entry_dt)
            except ValueError:
                entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                if entry_dt.tzinfo is None:
                    entry_dt = IST.localize(entry_dt)
                else:
                    entry_dt = entry_dt.astimezone(IST)
            hold_mins = int(
                (datetime.now(IST) - entry_dt).total_seconds() / 60
            )
            hold_str = f"{hold_mins} min"
        except Exception:
            hold_str = "unknown"
```
* **Replacement Content:**
```python
    def sell_decision(
        self,
        symbol: str,
        exit_reason: str,
        entry_price: float,
        exit_price: float,
        qty: int,
        gross_pnl: float,
        net_pnl: float,
        brokerage: float,
        entry_time: str,
        strategy: str,
        exit_time: str = "",
    ) -> None:
        """Log every sell with full P&L breakdown and hold time."""
        direction = "PROFIT" if net_pnl >= 0 else "LOSS"
        try:
            try:
                entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
                entry_dt = IST.localize(entry_dt)
            except ValueError:
                entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                if entry_dt.tzinfo is None:
                    entry_dt = IST.localize(entry_dt)
                else:
                    entry_dt = entry_dt.astimezone(IST)

            if exit_time:
                try:
                    exit_dt = datetime.strptime(exit_time, "%Y-%m-%d %H:%M:%S")
                    exit_dt = IST.localize(exit_dt)
                except ValueError:
                    exit_dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                    if exit_dt.tzinfo is None:
                        exit_dt = IST.localize(exit_dt)
                    else:
                        exit_dt = exit_dt.astimezone(IST)
            else:
                exit_dt = datetime.now(IST)

            hold_mins = int(
                (exit_dt - entry_dt).total_seconds() / 60
            )
            hold_str = f"{hold_mins} min"
        except Exception:
            hold_str = "unknown"
```

* **File:** `agents/agent_i6.py`
* **Line Range:** 128-137
* **Target Content:**
```python
                dlog.sell_decision(
                    symbol=sym, exit_reason="SL_HIT",
                    entry_price=pos["entry_price"], exit_price=fill_price,
                    qty=pos["qty"],
                    gross_pnl=gross_pnl,
                    net_pnl=gross_pnl - charges["total_charges"],
                    brokerage=charges["brokerage"],
                    entry_time=pos.get("entry_time", ""),
                    strategy=pos.get("strategy", ""),
                )
```
* **Replacement Content:**
```python
                dlog.sell_decision(
                    symbol=sym, exit_reason="SL_HIT",
                    entry_price=pos["entry_price"], exit_price=fill_price,
                    qty=pos["qty"],
                    gross_pnl=gross_pnl,
                    net_pnl=gross_pnl - charges["total_charges"],
                    brokerage=charges["brokerage"],
                    entry_time=pos.get("entry_time", ""),
                    strategy=pos.get("strategy", ""),
                    exit_time=current_time.strftime("%Y-%m-%d %H:%M:%S"),
                )
```

* **File:** `agents/agent_i6.py`
* **Line Range:** 150-159
* **Target Content:**
```python
                dlog.sell_decision(
                    symbol=sym, exit_reason="TARGET_HIT",
                    entry_price=pos["entry_price"], exit_price=fill_price,
                    qty=pos["qty"],
                    gross_pnl=gross_pnl,
                    net_pnl=gross_pnl - charges["total_charges"],
                    brokerage=charges["brokerage"],
                    entry_time=pos.get("entry_time", ""),
                    strategy=pos.get("strategy", ""),
                )
```
* **Replacement Content:**
```python
                dlog.sell_decision(
                    symbol=sym, exit_reason="TARGET_HIT",
                    entry_price=pos["entry_price"], exit_price=fill_price,
                    qty=pos["qty"],
                    gross_pnl=gross_pnl,
                    net_pnl=gross_pnl - charges["total_charges"],
                    brokerage=charges["brokerage"],
                    entry_time=pos.get("entry_time", ""),
                    strategy=pos.get("strategy", ""),
                    exit_time=current_time.strftime("%Y-%m-%d %H:%M:%S"),
                )
```

### 4. Isolate test log folders to prevent pollution in `tests/conftest.py`
* **File:** `tests/conftest.py`
* **Line Range:** 47-48
* **Target Content:**
```python
@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
```
* **Replacement Content:**
```python
@pytest.fixture(autouse=True)
def temp_logs(monkeypatch, tmp_path):
    """Ensure all tests use temporary directories for decisions and analytics logs, preventing pollution."""
    import utils.decision_logger
    import utils.analytics_logger
    monkeypatch.setattr(utils.decision_logger, "_DECISION_DIR", tmp_path / "decisions")
    monkeypatch.setattr(utils.analytics_logger, "ANALYTICS_DIR", tmp_path / "analytics")

@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
```

### 5. Wire session analytics logger into `execution/scheduler.py`
* **File:** `execution/scheduler.py`
* **Line Range:** 274-276
* **Target Content:**
```python
        if self._watchlist:
            self._portfolio.save_watchlist(self._watchlist)
```
* **Replacement Content:**
```python
        if self._watchlist:
            self._portfolio.save_watchlist(self._watchlist)

        try:
            from utils.analytics_logger import analytics
            bias_str = self._bias.bias if self._bias else "UNKNOWN"
            nifty_chg = 0.0
            if self._bias and hasattr(self._bias, "gift_nifty_gap_pct"):
                nifty_chg = self._bias.gift_nifty_gap_pct
            analytics.log_session_start(
                scan_count=len(self._candidate_pool) or 500,
                watchlist_count=len(self._watchlist),
                filters_applied={},
                market_bias=bias_str,
                nifty_chg_pct=nifty_chg,
                capital=self._portfolio.capital,
            )
        except Exception as ae:
            logger.debug("Analytics log_session_start failed (non-fatal): %s", ae)
```

* **File:** `execution/scheduler.py`
* **Line Range:** 372-376
* **Target Content:**
```python
    def run_post_market_review(self) -> None:
        """Run AgentI9 Claude Sonnet review after market close and backup DB."""
        reviewer = AgentI9(self._portfolio)
        reviewer.run()

        # Daily backup of portfolio.db
```
* **Replacement Content:**
```python
    def run_post_market_review(self) -> None:
        """Run AgentI9 Claude Sonnet review after market close and backup DB."""
        reviewer = AgentI9(self._portfolio)
        reviewer.run()

        try:
            from utils.analytics_logger import analytics
            report = self._portfolio.get_daily_report()
            trades = report.get("trades", [])
            total_trades = len(trades)
            winners = sum(1 for t in trades if t.get("net_pnl", 0.0) > 0)
            analytics.log_session_end(
                capital_at_close=self._portfolio.capital,
                session_pnl=report.get("daily_pnl", 0.0),
                total_trades=total_trades,
                winners=winners,
            )
        except Exception as ae:
            logger.debug("Analytics log_session_end failed (non-fatal): %s", ae)

        # Daily backup of portfolio.db
```

### 6. Fix `fake_i1` mock signature in `tests/test_orchestrator.py`
* **File:** `tests/test_orchestrator.py`
* **Line Range:** 59-60
* **Target Content:**
```python
    async def fake_i1():
        return []  # no candidates
```
* **Replacement Content:**
```python
    async def fake_i1(*args, **kwargs):
        return []  # no candidates
```
