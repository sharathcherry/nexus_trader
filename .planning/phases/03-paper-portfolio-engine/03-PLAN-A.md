---
wave: 1
plan_id: "03-PLAN-A"
phase: "03"
phase_name: "Paper Portfolio Engine"
objective: "Create execution/portfolio.py — PaperPortfolio with SQLite persistence, brokerage math, buy/sell/partial_exit, daily reset, halt logic"
depends_on: []
files_modified:
  - execution/portfolio.py
autonomous: true
requirements_addressed:
  - PORT-01
  - PORT-02
  - PORT-03
  - PORT-04
  - PORT-05
  - PORT-06
  - PORT-07
  - PORT-08
  - PORT-09
  - PORT-10
must_haves:
  truths:
    - "Buy 10 shares @ ₹500, sell @ ₹550 produces net_pnl = ₹494.586 (±₹0.01)"
    - "6th buy() call returns False when 5 positions already open"
    - "buy() returns False and logs WARNING when is_halted is True"
    - "daily_pnl crossing -2% of CAPITAL sets is_halted=True"
    - "Open positions survive process restart (re-init reads from SQLite)"
    - "execution/portfolio.db uses WAL journal mode"
    - "daily_pnl and trade_count reset to 0 on new trading day"
---

# Phase 3 Plan A: PaperPortfolio

## Tasks

### Task 1: Create execution/portfolio.py — DB init + schema

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-01 through D-06 — schema, WAL, meta table)
- .planning/phases/03-paper-portfolio-engine/03-RESEARCH.md §"SQLite WAL mode setup" and §"Schema DDL"
- config.py (config.CAPITAL, config.MAX_OPEN_POSITIONS, config.MAX_TRADES_PER_DAY, config.DAILY_LOSS_LIMIT_PCT)
- utils/logger.py (logger setup pattern)
</read_first>

<action>
Create `execution/portfolio.py`. Start with DB helper and schema creation:

- `DB_PATH = Path("execution/portfolio.db")`
- `_get_conn()` returns a connection with WAL mode, foreign keys ON, Row factory
- `PaperPortfolio.__init__()` calls `_create_tables()` then `_restore_state()`
- `_create_tables()` creates `positions`, `trades`, `meta` tables using IF NOT EXISTS DDL from RESEARCH.md §"Schema DDL"
- `_restore_state()` reads `capital`, `daily_pnl`, `trade_count`, `is_halted`, `force_squaredoff` from `meta` table. If `meta` is empty (first run), seeds with: `capital=config.CAPITAL`, `daily_pnl=0.0`, `trade_count=0`, `is_halted=0`, `force_squaredoff=0`, `last_trade_date=""`
- `_get_meta(key)` / `_set_meta(key, value)` helpers for meta table access

Include daily reset in `_restore_state()`: compare `last_trade_date` against today's IST date — if different, reset `daily_pnl`, `trade_count`, `is_halted`, `force_squaredoff`, `last_trade_date`.
</action>

<acceptance_criteria>
- `execution/portfolio.py` imports without error
- `PaperPortfolio()` creates `execution/portfolio.db` if absent
- `PRAGMA journal_mode=WAL` is set on every connection
- `python -c "from execution.portfolio import PaperPortfolio; p=PaperPortfolio(); print(p.capital)"` prints `100000`
- Re-initializing `PaperPortfolio()` a second time does not error (idempotent table creation)
- `meta` table contains `capital`, `daily_pnl`, `trade_count`, `is_halted`, `force_squaredoff`, `last_trade_date` after init
</acceptance_criteria>

---

### Task 2: Implement _calculate_brokerage() and properties

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-07, D-08, D-09 — brokerage formula)
- .planning/phases/03-paper-portfolio-engine/03-RESEARCH.md §"Zerodha brokerage calculation — verified formula"
- .planning/STATE.md §"Key Decisions Made" — exchange rate 0.0000307 correction
</read_first>

<action>
Add to `PaperPortfolio`:

```python
@property
def capital(self) -> float:
    return float(self._get_meta("capital"))

@property
def daily_pnl(self) -> float:
    return float(self._get_meta("daily_pnl"))

@property
def trade_count(self) -> int:
    return int(self._get_meta("trade_count"))

@property
def is_halted(self) -> bool:
    return self._get_meta("is_halted") == "1"
```

Add `_calculate_brokerage(buy_price, sell_price, qty)` using the exact formula from RESEARCH.md:
- turnover = (buy_price + sell_price) * qty
- brokerage = min(20.0, 0.0003 * turnover)
- stt = 0.00025 * sell_price * qty
- exchange_charges = 0.0000307 * turnover
- gst = 0.18 * brokerage
- total_charges = sum of all four

Returns dict with keys: `brokerage`, `stt`, `exchange_charges`, `gst`, `total_charges`. All values rounded to 4 decimal places.
</action>

<acceptance_criteria>
- `p._calculate_brokerage(500, 550, 10)["total_charges"]` equals `5.4144` (±0.001)
- `p._calculate_brokerage(500, 550, 10)["brokerage"]` equals `3.15`
- `p._calculate_brokerage(500, 550, 10)["stt"]` equals `1.375`
- `p._calculate_brokerage(500, 550, 10)["exchange_charges"]` equals `0.3224` (±0.001)
- Exchange rate used is `0.0000307` not `0.0000335`
- `p.capital` returns a float equal to `config.CAPITAL` on first run
- `p.is_halted` returns `False` on fresh init
</acceptance_criteria>

---

### Task 3: Implement buy()

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-12, D-13, D-15 — halt guard, return bool, terminal output)
- .planning/REQUIREMENTS.md (PORT-01, PORT-02)
- .planning/phases/03-paper-portfolio-engine/03-RESEARCH.md §"Schema DDL" (positions table columns)
</read_first>

<action>
Add `buy(symbol, entry_price, qty, stop_loss, target, strategy) -> bool` to `PaperPortfolio`:

Pre-checks (return `False` + WARNING log if any fail):
1. `is_halted` → "Trading halted — daily loss limit reached"
2. `len(open_positions) >= config.MAX_OPEN_POSITIONS` → "Max open positions reached"
3. `trade_count >= config.MAX_TRADES_PER_DAY` → "Max daily trades reached"
4. `symbol already in open_positions` → "Already holding {symbol}"

On success:
- Deduct cost from capital: `new_capital = capital - (entry_price * qty)`
- INSERT into `positions` table with all fields + `entry_time = now IST`
- Update `meta`: increment `trade_count`, update `capital`
- Log INFO: `"✅ BUY {symbol} qty={qty} @ ₹{entry_price:.2f} | SL=₹{stop_loss:.2f} | Target=₹{target:.2f} | Strategy={strategy}"`
- Return `True`

Helper `_get_open_positions() -> list[sqlite3.Row]` queries all rows from `positions` table.
</action>

<acceptance_criteria>
- `p.buy("RELIANCE.NS", 2500, 4, 2450, 2600, "GAP_AND_GO")` returns `True`
- Position appears in `positions` table after buy
- `p.capital` decreases by `2500 * 4 = 10000` after buy
- `p.trade_count` increments by 1 after buy
- Buying same symbol twice returns `False` second time
- After 5 buys, 6th `buy()` returns `False`
- `buy()` on halted portfolio returns `False` without touching DB
- Buy logs `"✅ BUY"` line to terminal
</acceptance_criteria>

---

### Task 4: Implement sell() with brokerage

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-09 — net_pnl formula, D-15 — terminal output)
- .planning/REQUIREMENTS.md (PORT-03, PORT-04)
- .planning/phases/03-paper-portfolio-engine/03-RESEARCH.md §"Zerodha brokerage calculation"
</read_first>

<action>
Add `sell(symbol, exit_price, qty, exit_reason="MANUAL") -> bool` to `PaperPortfolio`:

- Fetch position from `positions` table by symbol; return `False` if not found
- Call `_calculate_brokerage(position.entry_price, exit_price, qty)`
- `gross_pnl = (exit_price - position.entry_price) * qty`
- `net_pnl = gross_pnl - charges["total_charges"]`
- INSERT into `trades` table (all columns from schema)
- DELETE from `positions` table WHERE symbol=symbol
- Update `meta`:
  - `capital += (exit_price * qty) - charges["total_charges"]`
  - `daily_pnl += net_pnl`
- Check halt: if `daily_pnl < -(config.DAILY_LOSS_LIMIT_PCT * config.CAPITAL)`, set `is_halted=1` in meta
- Log INFO: `"❌ SELL {symbol} qty={qty} @ ₹{exit_price:.2f} | P&L=₹{net_pnl:.2f} | Reason={exit_reason}"`
- Return `True`
</action>

<acceptance_criteria>
- After buy@500/sell@550 for qty=10: `net_pnl` in trades table equals `494.586` (±0.01)
- Position removed from `positions` table after sell
- `p.capital` updated correctly after sell
- `p.daily_pnl` updated after sell
- When `daily_pnl` crosses `-2% of CAPITAL` (< -₹2000), `p.is_halted` becomes `True`
- Selling a symbol not in `positions` returns `False` without error
- Sell logs `"❌ SELL"` line to terminal
</acceptance_criteria>

---

### Task 5: Implement partial_exit() and update_stop_loss()

<read_first>
- .planning/REQUIREMENTS.md (PORT-05, PORT-06)
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-04 — write-through)
</read_first>

<action>
Add to `PaperPortfolio`:

`partial_exit(symbol, exit_price, exit_qty, exit_reason="PARTIAL_EXIT") -> bool`:
- Fetch position; return `False` if not found or `partial_exited=1` already
- Calculate brokerage on `exit_qty` shares
- INSERT into `trades` table for the partial quantity
- UPDATE `positions` SET `qty = qty - exit_qty`, `partial_exited = 1` WHERE symbol=symbol
- Update `meta`: adjust `capital`, `daily_pnl` for the exited portion
- Log INFO: `"⚡ PARTIAL EXIT {symbol} qty={exit_qty} @ ₹{exit_price:.2f} | P&L=₹{net_pnl:.2f}"`
- Return `True`

`update_stop_loss(symbol, new_stop_loss) -> bool`:
- Fetch position; return `False` if not found
- Only update if `new_stop_loss > position.stop_loss` (trail only upward)
- UPDATE `positions` SET `stop_loss = new_stop_loss` WHERE symbol=symbol
- Log DEBUG: `"⬆ TRAILING SL {symbol} → ₹{new_stop_loss:.2f}"`
- Return `True`
</action>

<acceptance_criteria>
- `partial_exit()` inserts a trade row for the partial qty
- `partial_exit()` updates position qty (halves it for 50% exit)
- `partial_exit()` sets `partial_exited=1` in positions table
- Calling `partial_exit()` twice on same position: second call returns `False` (already partially exited)
- `update_stop_loss()` only increases stop loss, never decreases
- `update_stop_loss()` with lower value returns `True` but leaves DB unchanged (or returns `False` — either is acceptable, as long as DB is not lowered)
</acceptance_criteria>

---

### Task 6: Implement get_portfolio_summary() and get_daily_report()

<read_first>
- .planning/REQUIREMENTS.md (PORT-07, PORT-08)
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-01 — schema, query targets)
</read_first>

<action>
Add to `PaperPortfolio`:

`get_portfolio_summary() -> dict`:
Returns:
```python
{
    "capital": float,
    "daily_pnl": float,
    "trade_count": int,
    "is_halted": bool,
    "open_positions": int,
    "positions": [{"symbol", "entry_price", "qty", "stop_loss", "target", "strategy", "entry_time", "partial_exited"}, ...]
}
```

`get_daily_report() -> dict`:
Queries `trades WHERE DATE(exit_time) = today`. Returns:
```python
{
    "date": str,
    "total_trades": int,
    "wins": int,
    "losses": int,
    "win_rate": float,  # wins / total_trades or 0.0
    "gross_pnl": float,
    "total_charges": float,
    "net_pnl": float,
    "best_trade": {"symbol", "net_pnl"} or None,
    "worst_trade": {"symbol", "net_pnl"} or None,
    "trades": [full trade list for today]
}
```
</action>

<acceptance_criteria>
- `get_portfolio_summary()` returns dict with all 6 keys
- `get_portfolio_summary()["open_positions"]` equals number of rows in `positions` table
- `get_daily_report()` returns dict with all 9 keys
- `get_daily_report()["win_rate"]` is `0.0` when `total_trades == 0` (no division by zero)
- `get_daily_report()["total_charges"]` sums all `total_charges` from today's trades
</acceptance_criteria>

---

### Task 7: Implement force_squareoff_all()

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-14 — idempotency, _squaredoff flag)
- .planning/STATE.md §"Key Decisions Made" — force_squareoff dual safety
- .planning/REQUIREMENTS.md (PORT-12 reference via OrderManager)
</read_first>

<action>
Add `force_squareoff_all(exit_price_map: dict[str, float]) -> int` to `PaperPortfolio`:

- Check `_get_meta("force_squaredoff") == "1"` — if True, log WARNING "Already squared off — skipping" and return 0
- Set `_set_meta("force_squaredoff", "1")` BEFORE closing any positions (prevents partial close on crash)
- For each open position: call `self.sell(symbol, exit_price_map.get(symbol, position.entry_price), position.qty, "FORCE_SQUAREOFF")`
- Return count of positions closed
- Log INFO: `"🔴 FORCE SQUAREOFF: closed {n} positions"`
</action>

<acceptance_criteria>
- `force_squareoff_all({"RELIANCE.NS": 2550})` closes all open positions
- Calling `force_squareoff_all()` twice: second call returns `0` and logs WARNING
- `positions` table is empty after successful force squareoff
- Each closed position has a trade record with `exit_reason="FORCE_SQUAREOFF"`
- `force_squaredoff` meta key is `"1"` after first call
</acceptance_criteria>
