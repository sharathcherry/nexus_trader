"""
execution/portfolio.py — PaperPortfolio

SQLite-backed paper trading portfolio with Zerodha brokerage math.
Handles buy/sell/partial_exit, daily reset, halt logic, force squareoff.

Schema decisions:
  D-01: Two-table schema (positions + trades) + meta key-value store
  D-02: WAL journal mode on every connection
  D-03: DB at execution/portfolio.db
  D-04: Write-through on every trade
  D-07/D-08: Exact Zerodha formula with exchange rate 0.0000307 (STATE.md correction)
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

import pytz

from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")
DB_PATH = Path("execution/portfolio.db")


def _get_conn() -> sqlite3.Connection:
    """Return a SQLite connection with WAL mode, Row factory, and foreign keys.

    check_same_thread=False is safe here because every caller wraps the
    connection in a context manager (with _get_conn() as conn:) so each
    logical operation gets its own short-lived connection.

    busy_timeout=5000 ms: Telegram bot polling and the scheduler both read the
    DB concurrently. WAL allows one writer + many readers, but a writer still
    briefly blocks readers on the WAL lock. 5s timeout prevents SQLITE_BUSY
    errors during the short write window.
    """
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,
        timeout=5.0,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # safe with WAL; faster than FULL
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


class PaperPortfolio:
    """
    Paper trading portfolio backed by SQLite.

    Persists open positions and closed trades across process restarts.
    Applies Zerodha brokerage math to every executed trade.
    Enforces daily loss halt and position/trade count limits.
    """

    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()
        self._restore_state()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create positions, trades, and meta tables if they do not exist."""
        with _get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol         TEXT    NOT NULL UNIQUE,
                    entry_price    REAL    NOT NULL,
                    qty            INTEGER NOT NULL,
                    stop_loss      REAL    NOT NULL,
                    target         REAL    NOT NULL,
                    strategy       TEXT    NOT NULL,
                    entry_time     TEXT    NOT NULL,
                    partial_exited INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol           TEXT    NOT NULL,
                    entry_price      REAL    NOT NULL,
                    exit_price       REAL    NOT NULL,
                    qty              INTEGER NOT NULL,
                    strategy         TEXT    NOT NULL,
                    entry_time       TEXT    NOT NULL,
                    exit_time        TEXT    NOT NULL,
                    gross_pnl        REAL    NOT NULL,
                    brokerage        REAL    NOT NULL,
                    stt              REAL    NOT NULL,
                    exchange_charges REAL    NOT NULL,
                    gst              REAL    NOT NULL,
                    total_charges    REAL    NOT NULL,
                    net_pnl          REAL    NOT NULL,
                    exit_reason      TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol        TEXT    PRIMARY KEY,
                    sector        TEXT    NOT NULL,
                    gap_pct       REAL    NOT NULL,
                    gap_score     REAL    NOT NULL,
                    strategy      TEXT    NOT NULL,
                    entry_trigger REAL    NOT NULL,
                    stop_loss     REAL    NOT NULL,
                    target        REAL    NOT NULL,
                    rr_ratio      REAL    NOT NULL,
                    catalyst_type TEXT    NOT NULL,
                    atr           REAL    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_reviews (
                    review_date                  TEXT PRIMARY KEY,
                    session_verdict              TEXT NOT NULL,
                    winning_strategies           TEXT NOT NULL,
                    underperforming_strategies   TEXT NOT NULL,
                    parameter_adjustments        TEXT NOT NULL,
                    tomorrow_watch               TEXT NOT NULL,
                    summary                      TEXT NOT NULL
                );
            """)

    # ------------------------------------------------------------------
    # Meta key-value helpers
    # ------------------------------------------------------------------

    def _get_meta(self, key: str) -> str:
        """Return meta value as string, or empty string if key missing."""
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        """Upsert a meta key-value pair."""
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    # ------------------------------------------------------------------
    # State restoration and daily reset
    # ------------------------------------------------------------------

    def _restore_state(self) -> None:
        """
        Seed meta table on first run, or reset daily fields on new trading day.
        """
        # Seed defaults if meta table is empty
        if not self._get_meta("capital"):
            self._set_meta("capital", str(float(config.CAPITAL)))
            self._set_meta("daily_pnl", "0.0")
            self._set_meta("trade_count", "0")
            self._set_meta("is_halted", "0")
            self._set_meta("force_squaredoff", "0")
            self._set_meta("last_trade_date", "")

        self.reset_daily_state_if_new_day()

    def reset_daily_state_if_new_day(self) -> None:
        """
        Reset daily fields if the stored last_trade_date differs from today.

        Cheap guard (one meta read) that only acts when last_trade_date != today.
        Called from __init__ (via _restore_state), buy(), sell(),
        force_squareoff_all(), and the 08:30 pre-market job so a long-running
        service rolls its daily state over without a restart.
        """
        today = datetime.now(IST).strftime("%Y-%m-%d")
        last_date = self._get_meta("last_trade_date")
        if last_date != today:
            self._set_meta("daily_pnl", "0.0")
            self._set_meta("trade_count", "0")
            self._set_meta("is_halted", "0")
            self._set_meta("force_squaredoff", "0")
            self._set_meta("last_trade_date", today)
            # Clear watchlist table on new day reset
            with _get_conn() as conn:
                conn.execute("DELETE FROM watchlist")
            logger.info("Daily state reset for %s", today)

    # ------------------------------------------------------------------
    # Properties (read from meta each time — write-through consistency)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_open_positions(self) -> list:
        """Return all rows from the positions table."""
        with _get_conn() as conn:
            rows = conn.execute("SELECT * FROM positions").fetchall()
        return rows

    def _get_position(self, symbol: str):
        """Return a single position row by symbol, or None."""
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE symbol = ?", (symbol,)
            ).fetchone()
        return row

    def _now_ist_str(self) -> str:
        """Return current IST datetime as ISO 8601 string."""
        return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    def _today_ist(self) -> str:
        """Return today's IST date as YYYY-MM-DD."""
        return datetime.now(IST).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Brokerage math (D-07, D-08 — Zerodha formula, exchange=0.0000307)
    # ------------------------------------------------------------------

    def _calculate_brokerage(
        self, buy_price: float, sell_price: float, qty: int
    ) -> dict:
        from utils.brokerage import calculate_brokerage
        return calculate_brokerage(buy_price, sell_price, qty)

    # ------------------------------------------------------------------
    # Core trading methods
    # ------------------------------------------------------------------

    def buy(
        self,
        symbol: str,
        entry_price: float,
        qty: int,
        stop_loss: float,
        target: float,
        strategy: str,
    ) -> bool:
        """
        Open a new paper position.

        Returns True on success, False on any rejection.
        All rejections are logged at WARNING level with reason.
        """
        self.reset_daily_state_if_new_day()
        from utils.telegram import notifier
        open_positions = self._get_open_positions()
        open_symbols = [row["symbol"] for row in open_positions]

        # Guard: halt
        if self.is_halted:
            reason = "Trading halted (daily loss limit reached)"
            logger.warning("BUY REJECTED %s — %s", symbol, reason)
            notifier.send_rejection(symbol, reason)
            return False

        # Guard: max open positions
        if len(open_positions) >= config.MAX_OPEN_POSITIONS:
            reason = f"Max open positions reached ({config.MAX_OPEN_POSITIONS})"
            logger.warning("BUY REJECTED %s — %s", symbol, reason)
            notifier.send_rejection(symbol, reason)
            return False

        # Guard: max trades per day
        if self.trade_count >= config.MAX_TRADES_PER_DAY:
            reason = f"Max daily trades reached ({config.MAX_TRADES_PER_DAY})"
            logger.warning("BUY REJECTED %s — %s", symbol, reason)
            notifier.send_rejection(symbol, reason)
            return False

        # Guard: already holding
        if symbol in open_symbols:
            reason = "Already holding this symbol"
            logger.warning("BUY REJECTED %s -- %s", symbol, reason)
            # Notifier might be spammy for this since signal evaluates multiple times, 
            # but per user request we notify when portfolio rejects buy order.
            # To reduce spam for already holding, maybe skip telegram or send it. Let's send.
            notifier.send_rejection(symbol, reason)
            return False

        # Guard: sector concentration (max MAX_POSITIONS_PER_SECTOR per sector)
        try:
            from data.universe import get_symbol_sector
            sector = get_symbol_sector(symbol)
            if sector:
                sector_count = sum(
                    1 for pos in open_positions
                    if get_symbol_sector(pos["symbol"]) == sector
                )
                if sector_count >= config.MAX_POSITIONS_PER_SECTOR:
                    reason = f"Sector concentration limit ({sector_count}/{config.MAX_POSITIONS_PER_SECTOR} in {sector})"
                    logger.warning("BUY REJECTED %s -- %s", symbol, reason)
                    notifier.send_rejection(symbol, reason)
                    return False
        except Exception:
            pass  # sector guard is best-effort; never block a trade on lookup failure

        entry_time = self._now_ist_str()
        cost = entry_price * qty

        with _get_conn() as conn:
            # Fetch current capital
            row = conn.execute("SELECT value FROM meta WHERE key = 'capital'").fetchone()
            current_capital = float(row["value"]) if row else float(config.CAPITAL)

            # Guard: negative capital check
            if current_capital < cost:
                reason = f"Insufficient capital. Required: Rs{cost:.2f}, Available: Rs{current_capital:.2f}"
                logger.warning("BUY REJECTED %s — %s", symbol, reason)
                notifier.send_rejection(symbol, reason)
                return False

            row = conn.execute("SELECT value FROM meta WHERE key = 'trade_count'").fetchone()
            current_trade_count = int(row["value"]) if row else 0

            new_capital = current_capital - cost
            new_trade_count = current_trade_count + 1

            conn.execute(
                """
                INSERT INTO positions
                  (symbol, entry_price, qty, stop_loss, target, strategy, entry_time, partial_exited)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (symbol, entry_price, qty, stop_loss, target, strategy, entry_time),
            )

            # Update meta: capital and trade_count inside transaction
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('capital', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_capital),),
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('trade_count', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_trade_count),),
            )

        logger.info(
            "BUY %s qty=%d @ Rs%.2f | SL=Rs%.2f | Target=Rs%.2f | Strategy=%s",
            symbol, qty, entry_price, stop_loss, target, strategy,
        )
        return True

    def sell(
        self,
        symbol: str,
        exit_price: float,
        qty: int,
        exit_reason: str = "MANUAL",
    ) -> bool:
        """
        Close (or partially close) a position.

        Returns True on success, False if position not found.
        """
        self.reset_daily_state_if_new_day()
        position = self._get_position(symbol)
        if position is None:
            logger.warning("SELL REJECTED %s — Symbol not in open positions", symbol)
            return False

        if qty > position["qty"]:
            logger.warning("SELL REJECTED %s — Qty %d > Position qty %d", symbol, qty, position["qty"])
            return False

        charges = self._calculate_brokerage(position["entry_price"], exit_price, qty)
        gross_pnl = (exit_price - position["entry_price"]) * qty
        net_pnl = gross_pnl - charges["total_charges"]
        exit_time = self._now_ist_str()
        proceeds = (exit_price * qty) - charges["total_charges"]

        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO trades
                  (symbol, entry_price, exit_price, qty, strategy,
                   entry_time, exit_time, gross_pnl, brokerage, stt,
                   exchange_charges, gst, total_charges, net_pnl, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    position["entry_price"],
                    exit_price,
                    qty,
                    position["strategy"],
                    position["entry_time"],
                    exit_time,
                    round(gross_pnl, 4),
                    charges["brokerage"],
                    charges["stt"],
                    charges["exchange_charges"],
                    charges["gst"],
                    charges["total_charges"],
                    round(net_pnl, 4),
                    exit_reason,
                ),
            )
            conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))

            # Update capital and daily_pnl inside transaction
            row = conn.execute("SELECT value FROM meta WHERE key = 'capital'").fetchone()
            current_capital = float(row["value"]) if row else float(config.CAPITAL)

            row = conn.execute("SELECT value FROM meta WHERE key = 'daily_pnl'").fetchone()
            current_daily_pnl = float(row["value"]) if row else 0.0

            new_capital = current_capital + proceeds
            new_daily_pnl = current_daily_pnl + net_pnl

            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('capital', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_capital),),
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('daily_pnl', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_daily_pnl),),
            )

            # Check halt threshold
            halt_threshold = -(config.DAILY_LOSS_LIMIT_PCT * config.CAPITAL)
            if new_daily_pnl < halt_threshold:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('is_halted', '1') "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                )
                logger.warning(
                    "TRADING HALTED — Daily P&L Rs%.2f crossed limit Rs%.2f",
                    new_daily_pnl,
                    halt_threshold,
                )

        pnl_sign = "+" if net_pnl >= 0 else ""
        logger.info(
            "SELL %s qty=%d @ Rs%.2f | P&L=Rs%s%.2f | Reason=%s",
            symbol, qty, exit_price, pnl_sign, net_pnl, exit_reason,
        )

        # Deep analytics logging (non-fatal)
        try:
            from utils.analytics_logger import analytics
            _pos = dict(position)  # sqlite3.Row has no .get() -- convert first
            analytics.log_trade(
                symbol=symbol,
                strategy=_pos.get("strategy", "UNKNOWN"),
                entry_price=_pos["entry_price"],
                fill_price=_pos["entry_price"],
                exit_price=exit_price,
                qty=qty,
                stop_loss=_pos.get("stop_loss", 0.0),
                target=_pos.get("target", 0.0),
                exit_reason=exit_reason,
                gross_pnl=round(gross_pnl, 4),
                brokerage=charges["brokerage"],        # brokerage only, not total
                net_pnl=round(net_pnl, 4),
                capital_before=current_capital,
                capital_after=new_capital,
                entry_time=_pos.get("entry_time", ""),
                exit_time=exit_time,
            )
        except Exception as _ae:
            logger.debug("Analytics log failed (non-fatal): %s", _ae)

        return True

    def force_squareoff_all(self, current_prices: dict[str, float] | None = None) -> int:
        """Close all open positions at market price. Idempotent."""
        # Must run BEFORE the idempotency check: a stale day-1
        # force_squaredoff flag would otherwise no-op day-2 squareoff.
        self.reset_daily_state_if_new_day()
        if current_prices is None:
            current_prices = {}

        if self._get_meta("force_squaredoff") == "1":
            logger.info("PaperPortfolio.force_squareoff_all: already executed (idempotency guard)")
            return 0

        self._set_meta("force_squaredoff", "1")
        summary = self.get_portfolio_summary()
        positions = summary.get("positions", [])
        if not positions:
            return 0

        closed_count = 0
        from utils.telegram import notifier
        for pos in positions:
            sym = pos["symbol"]
            price = current_prices.get(sym, pos["entry_price"])
            try:
                self.sell(sym, price, pos["qty"], "FORCE_SQUAREOFF")
                notifier.send_squareoff(sym, price, pos["qty"])
                closed_count += 1
            except Exception as e:
                logger.error("Failed to sell %s in force_squareoff_all: %s", sym, e)

        logger.info(f"PaperPortfolio: force squared off {closed_count} positions")
        return closed_count

    def partial_exit(
        self,
        symbol: str,
        exit_price: float,
        exit_qty: int,
        exit_reason: str = "PARTIAL_EXIT",
    ) -> bool:
        """
        Exit a portion of an open position (50% typical).

        Returns False if position not found or already partially exited.
        """
        position = self._get_position(symbol)
        if position is None:
            logger.warning(
                "PARTIAL EXIT REJECTED %s — Symbol not in open positions", symbol
            )
            return False

        if position["partial_exited"] == 1:
            logger.warning(
                "PARTIAL EXIT REJECTED %s — Already partially exited", symbol
            )
            return False

        charges = self._calculate_brokerage(
            position["entry_price"], exit_price, exit_qty
        )
        gross_pnl = (exit_price - position["entry_price"]) * exit_qty
        net_pnl = gross_pnl - charges["total_charges"]
        exit_time = self._now_ist_str()
        proceeds = (exit_price * exit_qty) - charges["total_charges"]

        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO trades
                  (symbol, entry_price, exit_price, qty, strategy,
                   entry_time, exit_time, gross_pnl, brokerage, stt,
                   exchange_charges, gst, total_charges, net_pnl, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    position["entry_price"],
                    exit_price,
                    exit_qty,
                    position["strategy"],
                    position["entry_time"],
                    exit_time,
                    round(gross_pnl, 4),
                    charges["brokerage"],
                    charges["stt"],
                    charges["exchange_charges"],
                    charges["gst"],
                    charges["total_charges"],
                    round(net_pnl, 4),
                    exit_reason,
                ),
            )
            conn.execute(
                """
                UPDATE positions
                SET qty = qty - ?, partial_exited = 1
                WHERE symbol = ?
                """,
                (exit_qty, symbol),
            )

            # Update capital and daily_pnl inside transaction
            row = conn.execute("SELECT value FROM meta WHERE key = 'capital'").fetchone()
            current_capital = float(row["value"]) if row else float(config.CAPITAL)

            row = conn.execute("SELECT value FROM meta WHERE key = 'daily_pnl'").fetchone()
            current_daily_pnl = float(row["value"]) if row else 0.0

            new_capital = current_capital + proceeds
            new_daily_pnl = current_daily_pnl + net_pnl

            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('capital', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_capital),),
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('daily_pnl', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(new_daily_pnl),),
            )

        pnl_sign = "+" if net_pnl >= 0 else ""
        logger.info(
            "PARTIAL EXIT %s qty=%d @ Rs%.2f | P&L=Rs%s%.2f",
            symbol, exit_qty, exit_price, pnl_sign, net_pnl,
        )
        return True

    def update_stop_loss(self, symbol: str, new_stop_loss: float) -> bool:
        """
        Trail the stop loss upward only.

        Returns True if position found; does not update if new SL is not higher.
        """
        position = self._get_position(symbol)
        if position is None:
            logger.warning(
                "UPDATE SL REJECTED %s — Symbol not in open positions", symbol
            )
            return False

        if new_stop_loss <= position["stop_loss"]:
            # Not an error — just a no-op (caller computed same or lower SL)
            return True

        with _get_conn() as conn:
            conn.execute(
                "UPDATE positions SET stop_loss = ? WHERE symbol = ?",
                (new_stop_loss, symbol),
            )

        logger.debug(
            "TRAILING SL %s -> Rs%.2f", symbol, new_stop_loss
        )
        return True

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_portfolio_summary(self) -> dict:
        """Return a snapshot of capital, open positions, and today's trades."""
        conn = _get_conn()
        if conn is None:
            return {"capital": float(config.CAPITAL), "positions": [], "trades": []}

        row = conn.execute("SELECT value FROM meta WHERE key = 'capital'").fetchone()
        capital = float(row["value"]) if row else float(config.CAPITAL)

        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM positions ORDER BY entry_time DESC"
        ).fetchall()]

        today = datetime.now(IST).strftime("%Y-%m-%d")
        trades = [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE exit_time LIKE ? ORDER BY exit_time DESC",
            (f"{today}%",),
        ).fetchall()]

        conn.close()
        return {"capital": capital, "positions": positions, "trades": trades}

    def get_daily_report(self) -> dict:
        """Return today P&L and trade list."""
        conn = _get_conn()
        if conn is None:
            return {"daily_pnl": 0.0, "trades": []}

        row = conn.execute("SELECT value FROM meta WHERE key = 'daily_pnl'").fetchone()
        daily_pnl = float(row["value"]) if row else 0.0

        today = datetime.now(IST).strftime("%Y-%m-%d")
        trades = [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE exit_time LIKE ? ORDER BY exit_time DESC",
            (f"{today}%",),
        ).fetchall()]

        conn.close()
        return {"daily_pnl": daily_pnl, "trades": trades}

    # ------------------------------------------------------------------
    # Watchlist persistence (called by scheduler + agent_i4)
    # ------------------------------------------------------------------

    def save_watchlist(self, watchlist: list) -> None:
        """Persist today's watchlist entries to DB for restart resilience."""
        with _get_conn() as conn:
            conn.execute("DELETE FROM watchlist")
            for e in watchlist:
                conn.execute(
                    """INSERT OR REPLACE INTO watchlist
                       (symbol, sector, gap_pct, gap_score, strategy,
                        entry_trigger, stop_loss, target, rr_ratio,
                        catalyst_type, atr)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        e.symbol,
                        getattr(e, "sector", "UNKNOWN"),
                        getattr(e, "gap_pct", 0.0),
                        getattr(e, "gap_score", 0.0),
                        e.strategy,
                        getattr(e, "entry_trigger", 0.0),
                        e.stop_loss,
                        e.target,
                        getattr(e, "rr_ratio", 0.0),
                        getattr(e, "catalyst_type", "UNKNOWN"),
                        getattr(e, "atr", 0.0),
                    ),
                )
        logger.info("Watchlist saved to DB: %d symbols", len(watchlist))

    def load_watchlist(self) -> list:
        """Restore watchlist from DB as WatchlistEntry objects."""
        from agents.models import WatchlistEntry
        with _get_conn() as conn:
            rows = conn.execute("SELECT * FROM watchlist").fetchall()
        entries = []
        for r in rows:
            try:
                entries.append(WatchlistEntry(
                    symbol=r["symbol"],
                    sector=r["sector"],
                    gap_pct=r["gap_pct"],
                    gap_score=r["gap_score"],
                    strategy=r["strategy"],
                    entry_trigger=r["entry_trigger"],
                    stop_loss=r["stop_loss"],
                    target=r["target"],
                    rr_ratio=r["rr_ratio"],
                    catalyst_type=r["catalyst_type"],
                    atr=r["atr"],
                ))
            except Exception as ex:
                logger.warning("Could not restore watchlist entry %s: %s", r["symbol"], ex)
        logger.info("Watchlist loaded from DB: %d symbols", len(entries))
        return entries

    def update_watchlist_trigger(self, symbol: str, new_trigger: float) -> None:
        """Update entry_trigger for a watchlist symbol (ORB override)."""
        with _get_conn() as conn:
            conn.execute(
                "UPDATE watchlist SET entry_trigger=? WHERE symbol=?",
                (new_trigger, symbol),
            )
        logger.debug("Watchlist trigger updated %s -> %.2f", symbol, new_trigger)

    # ------------------------------------------------------------------
    # Analytics queries (Telegram bot + dashboard)
    # ------------------------------------------------------------------

    def get_weekly_pnl(self) -> list:
        """Net P&L grouped by date for the last 7 calendar days."""
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT substr(exit_time,1,10) as date,
                          COUNT(*) as trades,
                          SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
                          ROUND(SUM(net_pnl),2) as net_pnl
                   FROM trades
                   WHERE exit_time >= date('now','-7 days')
                   GROUP BY date ORDER BY date DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_strategy_stats(self) -> list:
        """Win/loss/P&L breakdown per strategy, all-time."""
        with _get_conn() as conn:
            rows = conn.execute(
                """SELECT strategy,
                          COUNT(*) as trades,
                          SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
                          SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END) as losses,
                          ROUND(SUM(net_pnl),2) as pnl
                   FROM trades
                   GROUP BY strategy ORDER BY pnl DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def save_daily_review(
        self,
        review_date: str,
        verdict: str,
        winning_strategies: list,
        underperforming_strategies: list,
        parameter_adjustments: list,
        tomorrow_watch: list,
        summary: str,
    ) -> None:
        """Persist I9 daily review outputs to DB."""
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_reviews
                  (review_date, session_verdict, winning_strategies,
                   underperforming_strategies, parameter_adjustments,
                   tomorrow_watch, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_date,
                    verdict,
                    json.dumps(winning_strategies),
                    json.dumps(underperforming_strategies),
                    json.dumps(parameter_adjustments),
                    json.dumps(tomorrow_watch),
                    summary,
                ),
            )
        logger.info("Daily review saved for %s", review_date)
