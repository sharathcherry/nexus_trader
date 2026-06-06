# Phase 3: Paper Portfolio Engine - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Financial simulation core — buy/sell/partial_exit/trailing SL execute with accurate Zerodha brokerage math and SQLite-backed state that survives process restart. Delivers `execution/portfolio.py` (PaperPortfolio) and `execution/order_manager.py` (OrderManager). No agent logic, no scheduling, no signal generation.

</domain>

<decisions>
## Implementation Decisions

### SQLite schema
- **D-01:** Two-table schema in `execution/portfolio.db` (WAL mode):
  - `positions` table — open positions only. Columns: `id`, `symbol`, `entry_price`, `qty`, `stop_loss`, `target`, `strategy`, `entry_time`, `partial_exited` (bool).
  - `trades` table — all closed trades. Columns: `id`, `symbol`, `entry_price`, `exit_price`, `qty`, `strategy`, `entry_time`, `exit_time`, `gross_pnl`, `brokerage`, `net_pnl`, `exit_reason`.
  - `get_portfolio_summary()` queries `positions`; `get_daily_report()` queries `trades WHERE DATE(exit_time) = today`.
- **D-02:** SQLite WAL mode: `PRAGMA journal_mode=WAL` on connection open. Prevents read/write contention during concurrent polling.
- **D-03:** DB file path: `execution/portfolio.db`. Created on first init if absent.

### State persistence
- **D-04:** Write-through on every trade — every `buy()`, `sell()`, `partial_exit()`, `update_stop_loss()` immediately writes to SQLite within the same call. No background flush, no periodic save.
- **D-05:** `PaperPortfolio.__init__()` reads from SQLite to restore open positions and daily P&L. The `capital` and `daily_pnl` are stored in a `meta` table (key-value: `capital`, `daily_pnl`, `is_halted`, `trade_count`). On first run (empty DB), `capital` defaults to `config.CAPITAL`.
- **D-06:** `daily_pnl` resets to 0 and `trade_count` resets to 0 at the start of each trading day. Detection: compare stored `last_trade_date` in `meta` table against today's date on `__init__`. If different day, reset.

### Brokerage calculation
- **D-07:** Private `_calculate_brokerage(buy_price, sell_price, qty) -> dict` method inside `PaperPortfolio`. Returns breakdown dict: `{"brokerage": float, "stt": float, "exchange": float, "gst": float, "total_charges": float}`.
- **D-08:** Exact Zerodha formula (from STATE.md correction — exchange rate 0.0000307 not 0.0000335):
  - `turnover = (buy_price + sell_price) * qty`
  - `brokerage = min(20.0, 0.0003 * turnover)`  (0.03% of turnover, capped ₹20)
  - `stt = 0.00025 * sell_price * qty`  (0.025% sell-side only)
  - `exchange_charges = 0.0000307 * turnover`
  - `gst = 0.18 * brokerage`
  - `total_charges = brokerage + stt + exchange_charges + gst`
- **D-09:** `net_pnl = (sell_price - buy_price) * qty - total_charges`. Used in `sell()` and `partial_exit()`.

### PaperPortfolio / OrderManager coupling
- **D-10:** `OrderManager.__init__(self, portfolio: PaperPortfolio)` — stores reference as `self.portfolio`. All portfolio mutations go through `self.portfolio.buy()`, `.sell()`, etc. NexusTrader (Phase 5) instantiates both and injects.
- **D-11:** `OrderManager` is stateless except for `self.portfolio`. No DB access directly — all persistence is PaperPortfolio's responsibility.

### Halted state and guards
- **D-12:** `PaperPortfolio.is_halted` property reads from `meta` table. Set to `True` when `daily_pnl < -(config.DAILY_LOSS_LIMIT_PCT * config.CAPITAL)`. Once halted, all `buy()` calls return `False` with a WARNING log. Resets to `False` on new trading day (D-06).
- **D-13:** `buy()` returns `True` on success, `False` on rejection (halted, max positions, max trades). Never raises. All rejections log at WARNING level with reason.

### Force square-off idempotency
- **D-14:** `_squaredoff` flag (bool, stored in `meta` as `force_squaredoff`) prevents double-close. `force_squareoff_all()` checks flag first — if `True`, logs and returns immediately. Sets flag to `True` before closing positions. `OrderManager.check_and_execute_exits()` also checks 15:15 time gate.

### Terminal output
- **D-15:** PORT-10 colored terminal logs use `logger` with colorlog (no custom levels yet — Phase 5 adds TRADE level). Use INFO level for buy/sell/exit events with emoji prefix in the message string: `"✅ BUY RELIANCE.NS ..."`, `"❌ SELL ..."`, `"⚠️ SL HIT ..."`.

### Claude's Discretion
- Exact SQLite column types (TEXT vs REAL vs INTEGER)
- Whether to use `sqlite3` directly or wrap with a thin connection manager
- Trailing stop update logic detail for GAP_AND_GO (0.75 ATR) and ORB (breakeven at 1:1) — those exact values are in PORT-13 and REQUIREMENTS.md

</decisions>

<specifics>
## Specific Ideas

- STATE.md correction: exchange charge rate is 0.0000307 (not 0.0000335 from PROJECT.md). The Phase 3 success criterion explicitly tests brokerage math "to the rupee" — use 0.0000307.
- Success criterion test: buy 10 shares at ₹500, sell at ₹550. Manual calculation with 0.0000307 rate must match `get_daily_report()` output exactly.
- PORT-09 explicitly says "JSON for continuity across days" in REQUIREMENTS.md but STATE.md decision is SQLite WAL. SQLite supersedes JSON — use SQLite, ignore the JSON reference in REQUIREMENTS.md (it's superseded by the architectural decision).

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Brokerage math and architectural decisions
- `.planning/STATE.md` §"Key Decisions Made" — SQLite WAL mode decision, exchange charge rate correction (0.0000307), force_squareoff dual safety pattern
- `.planning/REQUIREMENTS.md` §"Paper Portfolio Engine" (PORT-01 through PORT-13) — complete requirement set

### Phase context
- `.planning/phases/01-foundation/01-CONTEXT.md` — import patterns, config singleton, logger setup
- `.planning/ROADMAP.md` §"Phase 3: Paper Portfolio Engine" — success criteria (4 items) that define done

### Brokerage formula reference
- `CLAUDE.md` §"Project Constraints" — Zerodha brokerage components listed (cross-check against STATE.md correction)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `config.py` — `config.CAPITAL`, `config.MAX_OPEN_POSITIONS`, `config.MAX_TRADES_PER_DAY`, `config.DAILY_LOSS_LIMIT_PCT`, `config.RISK_PER_TRADE_PCT` all used by PaperPortfolio
- `utils/logger.py` — `setup_logger(__name__)` at module level in portfolio.py and order_manager.py

### Established Patterns
- Import pattern: `from config import config`, `from utils.logger import setup_logger`
- Error contract: methods return bool/None/empty on failure, no exceptions to callers

### Integration Points
- `PaperPortfolio` ← `OrderManager` (Phase 3 internal)
- `OrderManager` ← `AgentI4` signal engine (Phase 4b calls `check_and_execute_exits()`)
- `OrderManager.calculate_quantity()` ← `AgentI3` watchlist ranker (Phase 4a uses risk sizing)
- `PaperPortfolio.get_daily_report()` ← `AgentI9` Claude reviewer (Phase 4c)
- `force_squareoff_all()` ← APScheduler 15:15 job AND market loop time check (Phase 5)

</code_context>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-paper-portfolio-engine*
*Context gathered: 2026-06-06*
