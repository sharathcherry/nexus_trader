# Phase 3: Paper Portfolio Engine - Research

**Researched:** 2026-06-06
**Phase:** 03-paper-portfolio-engine

## RESEARCH COMPLETE

---

## 1. SQLite WAL mode setup

```python
import sqlite3
from pathlib import Path

DB_PATH = Path("execution/portfolio.db")

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row   # dict-like row access
    return conn
```

`detect_types=PARSE_DECLTYPES` allows storing Python `datetime` objects as TEXT automatically.
`conn.row_factory = sqlite3.Row` means rows support both `row["column"]` and `row[0]` access.

---

## 2. Schema DDL

```sql
-- Open positions only
CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL UNIQUE,
    entry_price REAL NOT NULL,
    qty         INTEGER NOT NULL,
    stop_loss   REAL NOT NULL,
    target      REAL NOT NULL,
    strategy    TEXT NOT NULL,
    entry_time  TEXT NOT NULL,   -- ISO8601 string
    partial_exited INTEGER NOT NULL DEFAULT 0  -- 0=False, 1=True
);

-- All closed trades
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    exit_price      REAL NOT NULL,
    qty             INTEGER NOT NULL,
    strategy        TEXT NOT NULL,
    entry_time      TEXT NOT NULL,
    exit_time       TEXT NOT NULL,
    gross_pnl       REAL NOT NULL,
    brokerage       REAL NOT NULL,
    stt             REAL NOT NULL,
    exchange_charges REAL NOT NULL,
    gst             REAL NOT NULL,
    total_charges   REAL NOT NULL,
    net_pnl         REAL NOT NULL,
    exit_reason     TEXT NOT NULL   -- 'TARGET', 'STOP_LOSS', 'FORCE_SQUAREOFF', 'PARTIAL_EXIT'
);

-- Key-value state store
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Meta keys: `capital`, `daily_pnl`, `trade_count`, `is_halted`, `force_squaredoff`, `last_trade_date`.

---

## 3. Zerodha brokerage calculation — verified formula

From STATE.md (corrected exchange rate 0.0000307):

```python
def _calculate_brokerage(self, buy_price: float, sell_price: float, qty: int) -> dict:
    buy_turnover  = buy_price * qty
    sell_turnover = sell_price * qty
    turnover      = buy_turnover + sell_turnover

    brokerage  = min(20.0, 0.0003 * turnover)         # 0.03% of total turnover, capped ₹20
    stt        = 0.00025 * sell_turnover               # 0.025% sell-side only
    exchange   = 0.0000307 * turnover                  # exchange charges (corrected rate)
    gst        = 0.18 * brokerage                      # 18% GST on brokerage only

    total = brokerage + stt + exchange + gst

    return {
        "brokerage":        round(brokerage, 4),
        "stt":              round(stt, 4),
        "exchange_charges": round(exchange, 4),
        "gst":              round(gst, 4),
        "total_charges":    round(total, 4),
    }
```

**Manual verification (Phase 3 success criterion):**
- Buy 10 @ ₹500: buy_turnover = ₹5,000
- Sell 10 @ ₹550: sell_turnover = ₹5,500; total turnover = ₹10,500
- brokerage = min(20, 0.0003 × 10500) = min(20, 3.15) = ₹3.15
- STT = 0.00025 × 5500 = ₹1.375
- exchange = 0.0000307 × 10500 = ₹0.32235
- GST = 0.18 × 3.15 = ₹0.567
- total_charges = 3.15 + 1.375 + 0.32235 + 0.567 = **₹5.41435**
- gross_pnl = (550 - 500) × 10 = ₹500
- net_pnl = 500 - 5.41435 = **₹494.586**

---

## 4. Position quantity sizing (PORT-11)

```python
def calculate_quantity(self, entry_price: float, stop_loss: float) -> int:
    risk_amount   = config.CAPITAL * config.RISK_PER_TRADE_PCT   # ₹1,000 default
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        return 0
    qty = int(risk_amount / risk_per_share)
    # Cap at 10% of capital
    max_qty = int((config.CAPITAL * 0.10) / entry_price)
    return min(qty, max_qty)
```

---

## 5. Trailing stop logic (PORT-13)

Two strategies with different trailing rules:

**GAP_AND_GO:** Trail at 0.75 ATR below current price once position is 1 ATR in profit.
```python
if current_price >= entry_price + atr:          # 1 ATR in profit
    new_sl = current_price - (0.75 * atr)
    if new_sl > position.stop_loss:             # only trail up, never down
        update_stop_loss(symbol, new_sl)
```

**ORB_BREAKOUT:** Move SL to breakeven (entry_price) once 1:1 R:R is reached.
```python
reward = position.target - position.entry_price
if current_price >= position.entry_price + reward:  # 1:1 R:R
    if position.entry_price > position.stop_loss:    # only if not already at BE
        update_stop_loss(symbol, position.entry_price)
```

---

## 6. Partial exit at 1:1 R:R (PORT-05, PORT-12)

```python
# In OrderManager.check_and_execute_exits():
reward   = position.target - position.entry_price
half_way = position.entry_price + reward          # 1:1 R:R point

if current_price >= half_way and not position.partial_exited:
    exit_qty = position.qty // 2
    portfolio.partial_exit(symbol, current_price, exit_qty, "PARTIAL_EXIT")
```

`partial_exit()` closes half the position, records a trade row, updates qty in `positions` table, sets `partial_exited=1`.

---

## 7. Daily reset logic

```python
# In PaperPortfolio.__init__():
last_date = self._get_meta("last_trade_date")
today = datetime.now(IST).strftime("%Y-%m-%d")

if last_date != today:
    self._set_meta("daily_pnl", "0.0")
    self._set_meta("trade_count", "0")
    self._set_meta("is_halted", "0")
    self._set_meta("force_squaredoff", "0")
    self._set_meta("last_trade_date", today)
```

---

## Validation Architecture

| Criterion | Test |
|-----------|------|
| Buy 10@500, sell@550 — net P&L matches manual calc | `assert abs(net_pnl - 494.586) < 0.01` |
| 6th buy rejected after 5 open positions | `assert portfolio.buy(...) is False` after 5 buys |
| Daily P&L -2% triggers is_halted | After loss > ₹2,000, all buys rejected |
| State survives process restart | Write buy, re-init PaperPortfolio, assert position still present |
| force_squareoff_all() idempotent | Call twice, assert only one trade record per position |
