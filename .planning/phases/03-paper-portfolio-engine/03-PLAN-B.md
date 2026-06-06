---
wave: 2
plan_id: "03-PLAN-B"
phase: "03"
phase_name: "Paper Portfolio Engine"
objective: "Create execution/order_manager.py — OrderManager with quantity sizing, exit checks, trailing stop logic"
depends_on:
  - "03-PLAN-A"
files_modified:
  - execution/order_manager.py
autonomous: true
requirements_addressed:
  - PORT-11
  - PORT-12
  - PORT-13
must_haves:
  truths:
    - "calculate_quantity() sizes by 1% risk per trade, capped at 10% capital"
    - "check_and_execute_exits() closes position on target hit"
    - "check_and_execute_exits() closes position on stop_loss hit"
    - "check_and_execute_exits() calls force_squareoff_all() at or after 15:15 IST"
    - "force_squareoff_all() called twice produces only one trade record per position (idempotent)"
    - "GAP_AND_GO trailing stop trails at 0.75 ATR once 1 ATR in profit"
    - "ORB_BREAKOUT SL moves to entry_price at 1:1 R:R"
---

# Phase 3 Plan B: OrderManager

## Tasks

### Task 1: Create execution/order_manager.py — skeleton + calculate_quantity()

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-10, D-11 — coupling pattern)
- .planning/phases/03-paper-portfolio-engine/03-RESEARCH.md §"Position quantity sizing"
- .planning/REQUIREMENTS.md (PORT-11)
- config.py (config.RISK_PER_TRADE_PCT, config.CAPITAL)
</read_first>

<action>
Create `execution/order_manager.py`:

```python
from execution.portfolio import PaperPortfolio
from config import config
from utils.logger import setup_logger
import pytz
from datetime import datetime

logger = setup_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class OrderManager:
    def __init__(self, portfolio: PaperPortfolio):
        self.portfolio = portfolio
```

Add `calculate_quantity(entry_price, stop_loss) -> int`:
- `risk_amount = config.CAPITAL * config.RISK_PER_TRADE_PCT`
- `risk_per_share = abs(entry_price - stop_loss)`
- If `risk_per_share <= 0`: return 0
- `qty = int(risk_amount / risk_per_share)`
- Cap: `max_qty = int((config.CAPITAL * 0.10) / entry_price)`
- Return `min(qty, max_qty)`
</action>

<acceptance_criteria>
- `execution/order_manager.py` imports without error
- `OrderManager(portfolio)` instantiates without error
- `calculate_quantity(2500, 2450)` returns `int(1000/50) = 20` (risk=₹1000, risk/share=₹50)
- `calculate_quantity(500, 490)` returns `int(1000/10) = 100`, but capped at `int(10000/500)=20`
- `calculate_quantity(500, 500)` returns `0` (zero risk_per_share)
- Return type is always `int`, never `float`
</acceptance_criteria>

---

### Task 2: Implement check_and_execute_exits()

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-CONTEXT.md (D-14 — force squareoff idempotency)
- .planning/phases/03-paper-portfolio-engine/03-RESEARCH.md §"Partial exit at 1:1 R:R"
- .planning/REQUIREMENTS.md (PORT-12)
- .planning/STATE.md §"Key Decisions Made" — force_squareoff dual safety (loop time check)
</read_first>

<action>
Add `check_and_execute_exits(live_prices: dict[str, float]) -> None` to `OrderManager`:

Called every polling cycle (60s) during market session. For each open position:

1. **Force squareoff gate:** Check current IST time. If `now.hour > 15 or (now.hour == 15 and now.minute >= 15)`:
   - Call `self.portfolio.force_squareoff_all(live_prices)`
   - Return immediately (all positions closed)

2. **For each position** (skip if not in `live_prices`):
   - `current_price = live_prices[symbol]`
   - **Target hit:** if `current_price >= position.target` → `portfolio.sell(symbol, current_price, position.qty, "TARGET")`
   - **Stop loss hit:** if `current_price <= position.stop_loss` → `portfolio.sell(symbol, current_price, position.qty, "STOP_LOSS")`
   - **Partial exit (1:1 R:R):** if not `position.partial_exited`:
     - `reward = position.target - position.entry_price`
     - if `current_price >= position.entry_price + reward`:
       - `portfolio.partial_exit(symbol, current_price, position.qty // 2)`

3. **Circuit breaker flag:** if price is unchanged for 3 consecutive calls, log WARNING `"⚠️ POSSIBLE_CIRCUIT {symbol} — price unchanged 3 cycles"`. Track per-symbol with a `_price_history: dict[str, list]` on the OrderManager instance.
</action>

<acceptance_criteria>
- Position with `target=2600` and `current_price=2600` gets sold with reason="TARGET"
- Position with `stop_loss=2450` and `current_price=2440` gets sold with reason="STOP_LOSS"
- At 15:15 IST, `force_squareoff_all()` is called regardless of individual position state
- Partial exit fires when price reaches entry + (target - entry)
- After partial exit, full target/SL checks still run on remaining qty
- Price unchanged for 3 cycles → WARNING log containing "POSSIBLE_CIRCUIT"
- `check_and_execute_exits()` never raises — all errors caught and logged
</acceptance_criteria>

---

### Task 3: Implement update_trailing_stops()

<read_first>
- .planning/phases/03-paper-portfolio-engine/03-RESEARCH.md §"Trailing stop logic"
- .planning/REQUIREMENTS.md (PORT-13)
</read_first>

<action>
Add `update_trailing_stops(live_prices: dict[str, float], atrs: dict[str, float]) -> None` to `OrderManager`:

Called every polling cycle after `check_and_execute_exits()`. For each open position:

**GAP_AND_GO strategy:**
```python
if position.strategy == "GAP_AND_GO" and symbol in atrs:
    atr = atrs[symbol]
    if current_price >= position.entry_price + atr:      # 1 ATR in profit
        new_sl = current_price - (0.75 * atr)
        if new_sl > position.stop_loss:
            self.portfolio.update_stop_loss(symbol, new_sl)
```

**ORB_BREAKOUT strategy:**
```python
if position.strategy == "ORB_BREAKOUT":
    reward = position.target - position.entry_price
    if current_price >= position.entry_price + reward:   # 1:1 R:R
        if position.entry_price > position.stop_loss:    # not yet at breakeven
            self.portfolio.update_stop_loss(symbol, position.entry_price)
```

Other strategies (GAP_FILL, VWAP_RECLAIM): no trailing stop — leave SL unchanged.
</action>

<acceptance_criteria>
- GAP_AND_GO position: when `current_price = entry + 1.5*ATR`, new SL = `current_price - 0.75*ATR`
- GAP_AND_GO: SL never decreases — if new computed SL < existing SL, no update
- ORB_BREAKOUT: at 1:1 R:R, SL moves to entry_price exactly
- ORB_BREAKOUT: once SL already equals entry_price, no further update
- GAP_FILL strategy: `update_trailing_stops()` makes no changes
- Method never raises — missing symbol in `atrs` is handled gracefully
</acceptance_criteria>

---

## Verification

```bash
# Full integration test — no network required
python -c "
import os, sqlite3
# Clean slate
if os.path.exists('execution/portfolio.db'):
    os.remove('execution/portfolio.db')

from execution.portfolio import PaperPortfolio
from execution.order_manager import OrderManager
from config import config

p = PaperPortfolio()
om = OrderManager(p)

# Test quantity sizing
qty = om.calculate_quantity(2500, 2450)
assert qty == 20, f'Expected 20, got {qty}'

# Test buy
result = p.buy('RELIANCE.NS', 500, 10, 470, 560, 'GAP_AND_GO')
assert result is True

# Test brokerage precision
p.sell('RELIANCE.NS', 550, 10, 'TARGET')
report = p.get_daily_report()
net = report['trades'][0]['net_pnl']
assert abs(net - 494.586) < 0.01, f'Net PNL mismatch: {net}'

# Test halt at -2%
p2 = PaperPortfolio()
import os; os.remove('execution/portfolio.db')
p2 = PaperPortfolio()
p2.buy('TEST.NS', 500, 400, 450, 560, 'GAP_AND_GO')  # 400 shares
p2.sell('TEST.NS', 495, 400, 'STOP_LOSS')             # loss > 2k triggers halt
assert p2.is_halted, f'Expected halted after big loss'
assert p2.buy('MORE.NS', 100, 10, 90, 110, 'GAP_AND_GO') is False

# Test idempotent squareoff
p3 = PaperPortfolio()
p3.buy('INFY.NS', 1500, 5, 1450, 1600, 'ORB_BREAKOUT')
n1 = p3.force_squareoff_all({'INFY.NS': 1520})
n2 = p3.force_squareoff_all({'INFY.NS': 1520})
assert n1 == 1 and n2 == 0, f'Idempotency failed: {n1}, {n2}'

# Test state survives restart
p4 = PaperPortfolio()
p4.buy('WIPRO.NS', 300, 20, 285, 330, 'VWAP_RECLAIM')
del p4
p5 = PaperPortfolio()
summary = p5.get_portfolio_summary()
symbols = [pos['symbol'] for pos in summary['positions']]
assert 'WIPRO.NS' in symbols, 'Position lost on restart'

print('All Phase 3 tests passed')
"
```
