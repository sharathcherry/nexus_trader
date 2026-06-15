"""
utils/analytics_logger.py -- Deep structured logging for nexus_trader.

Writes three complementary log streams:
  1. logs/analytics/trades_YYYYMMDD.json  -- one JSON object per trade, 20+ fields
  2. logs/analytics/session_YYYYMMDD.json -- full session summary (pre/post market)
  3. logs/analytics/analytics.json        -- rolling all-time stats (updated live)

All timestamps are IST. Designed to be read by the Telegram chat AI for analysis.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Any

import pytz

IST = pytz.timezone("Asia/Kolkata")
ANALYTICS_DIR = Path("logs/analytics")
DB_PATH       = Path("execution/portfolio.db")


def _now_ist() -> datetime:
    return datetime.now(IST)

def _today() -> str:
    return _now_ist().strftime("%Y%m%d")

def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None

def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


class AnalyticsLogger:
    """
    Central structured logger.  Wire into portfolio.sell() and pre/post-market
    hooks for complete coverage.
    """

    def __init__(self) -> None:
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Trade logging
    # ------------------------------------------------------------------

    def log_trade(
        self,
        symbol: str,
        strategy: str,
        entry_price: float,
        fill_price: float,       # entry with slippage applied
        exit_price: float,
        qty: int,
        stop_loss: float,
        target: float,
        exit_reason: str,
        gross_pnl: float,
        brokerage: float,
        net_pnl: float,
        capital_before: float,
        capital_after: float,
        entry_time: str,
        exit_time: str,
        gap_pct: float = 0.0,
        market_bias: str = "UNKNOWN",
        nifty_chg_pct: float = 0.0,
        extra: dict | None = None,
    ) -> None:
        """Append one trade record to today's trade log and update analytics.json."""
        # Derived metrics
        hold_mins = 0
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            t_in  = datetime.strptime(entry_time[:19], fmt)
            t_out = datetime.strptime(exit_time[:19], fmt)
            hold_mins = int((t_out - t_in).total_seconds() / 60)
        except Exception:
            pass

        planned_rr = 0.0
        if entry_price > stop_loss:
            risk = entry_price - stop_loss
            reward = target - entry_price
            planned_rr = round(reward / risk, 2) if risk > 0 else 0.0

        realized_rr = 0.0
        if entry_price > stop_loss:
            risk = entry_price - stop_loss
            realized_rr = round((exit_price - entry_price) / risk, 2) if risk > 0 else 0.0

        slippage_rs = round((fill_price - entry_price) * qty, 2)
        won = net_pnl > 0

        record = {
            "ts":              _now_ist().isoformat(),
            "date":            exit_time[:10],
            "symbol":          symbol,
            "strategy":        strategy,
            "market_bias":     market_bias,
            "gap_pct":         round(gap_pct, 3),
            "nifty_chg_pct":   round(nifty_chg_pct, 3),
            "entry_price":     entry_price,
            "fill_price":      fill_price,
            "exit_price":      exit_price,
            "stop_loss":       stop_loss,
            "target":          target,
            "qty":             qty,
            "exit_reason":     exit_reason,
            "hold_minutes":    hold_mins,
            "planned_rr":      planned_rr,
            "realized_rr":     realized_rr,
            "slippage_rs":     slippage_rs,
            "gross_pnl":       round(gross_pnl, 2),
            "brokerage":       round(brokerage, 2),
            "net_pnl":         round(net_pnl, 2),
            "capital_before":  round(capital_before, 2),
            "capital_after":   round(capital_after, 2),
            "won":             won,
            **(extra or {}),
        }

        trade_path = ANALYTICS_DIR / f"trades_{_today()}.json"
        existing   = _load_json(trade_path) or []
        existing.append(record)
        _save_json(trade_path, existing)

        self._update_rolling(record)

    # ------------------------------------------------------------------
    # Session logging
    # ------------------------------------------------------------------

    def log_session_start(
        self,
        scan_count: int,
        watchlist_count: int,
        filters_applied: dict[str, int],
        market_bias: str,
        nifty_chg_pct: float,
        capital: float,
    ) -> None:
        """Called at end of pre-market pipeline."""
        session = {
            "date":             _today(),
            "session_start_ts": _now_ist().isoformat(),
            "capital_at_open":  round(capital, 2),
            "market_bias":      market_bias,
            "nifty_chg_pct":    round(nifty_chg_pct, 3),
            "stocks_scanned":   scan_count,
            "watchlist_count":  watchlist_count,
            "filter_rejections": filters_applied,
            "trades":           [],
            "session_pnl":      0.0,
            "capital_at_close": round(capital, 2),
        }
        _save_json(ANALYTICS_DIR / f"session_{_today()}.json", session)

    def log_session_end(
        self,
        capital_at_close: float,
        session_pnl: float,
        total_trades: int,
        winners: int,
    ) -> None:
        """Called at end of post-market review."""
        path = ANALYTICS_DIR / f"session_{_today()}.json"
        session = _load_json(path) or {}
        session.update({
            "session_end_ts":  _now_ist().isoformat(),
            "capital_at_close": round(capital_at_close, 2),
            "session_pnl":     round(session_pnl, 2),
            "total_trades":    total_trades,
            "winners":         winners,
            "losers":          total_trades - winners,
            "win_rate_pct":    round(winners / total_trades * 100, 1) if total_trades else 0.0,
        })
        _save_json(path, session)

    # ------------------------------------------------------------------
    # Rolling analytics
    # ------------------------------------------------------------------

    def _update_rolling(self, trade: dict) -> None:
        """Merge one trade into analytics.json rolling stats."""
        path = ANALYTICS_DIR / "analytics.json"
        a = _load_json(path) or {
            "total_trades": 0, "winners": 0, "losers": 0,
            "total_net_pnl": 0.0, "total_brokerage": 0.0,
            "total_slippage_rs": 0.0, "total_hold_minutes": 0,
            "best_trade": None, "worst_trade": None,
            "by_strategy": {}, "by_exit_reason": {},
            "by_bias": {}, "avg_realized_rr": 0.0,
            "last_updated": "",
        }

        a["total_trades"]       += 1
        a["winners"]            += 1 if trade["won"] else 0
        a["losers"]             += 0 if trade["won"] else 1
        a["total_net_pnl"]      = round(a["total_net_pnl"] + trade["net_pnl"], 2)
        a["total_brokerage"]    = round(a["total_brokerage"] + trade["brokerage"], 2)
        a["total_slippage_rs"]  = round(a["total_slippage_rs"] + trade["slippage_rs"], 2)
        a["total_hold_minutes"] += trade["hold_minutes"]
        a["last_updated"]       = _now_ist().isoformat()

        # Rolling avg RR
        n = a["total_trades"]
        prev_avg = a.get("avg_realized_rr", 0.0)
        a["avg_realized_rr"] = round(prev_avg + (trade["realized_rr"] - prev_avg) / n, 3)

        # Best / worst trade
        def _is_better(new, old):
            return old is None or new["net_pnl"] > old["net_pnl"]
        def _is_worse(new, old):
            return old is None or new["net_pnl"] < old["net_pnl"]
        snap = {k: trade[k] for k in ("symbol","strategy","net_pnl","exit_reason","date")}
        if _is_better(snap, a["best_trade"]):  a["best_trade"]  = snap
        if _is_worse(snap, a["worst_trade"]): a["worst_trade"] = snap

        # By strategy
        s = trade["strategy"]
        bs = a["by_strategy"].setdefault(s, {"trades":0,"winners":0,"net_pnl":0.0})
        bs["trades"] += 1; bs["winners"] += 1 if trade["won"] else 0
        bs["net_pnl"] = round(bs["net_pnl"] + trade["net_pnl"], 2)

        # By exit reason
        er = trade["exit_reason"]
        be = a["by_exit_reason"].setdefault(er, {"count":0,"net_pnl":0.0})
        be["count"] += 1; be["net_pnl"] = round(be["net_pnl"] + trade["net_pnl"], 2)

        # By market bias
        bias = trade.get("market_bias","UNKNOWN")
        bb = a["by_bias"].setdefault(bias, {"trades":0,"net_pnl":0.0})
        bb["trades"] += 1; bb["net_pnl"] = round(bb["net_pnl"] + trade["net_pnl"], 2)

        _save_json(path, a)

    # ------------------------------------------------------------------
    # Context builder (for Telegram AI)
    # ------------------------------------------------------------------

    def get_context_for_ai(self, max_log_lines: int = 60) -> dict:
        """
        Return a structured dict with everything the Telegram AI needs to
        answer questions about trades, logs, and system health.
        """
        ctx: dict = {}

        # Rolling analytics
        ctx["analytics"] = _load_json(ANALYTICS_DIR / "analytics.json") or {}

        # Today's session
        ctx["today_session"] = _load_json(ANALYTICS_DIR / f"session_{_today()}.json") or {}

        # Today's trades (full detail)
        ctx["today_trades"] = _load_json(ANALYTICS_DIR / f"trades_{_today()}.json") or []

        # Last 7 days trade files (summary only to keep context small)
        weekly: list[dict] = []
        for f in sorted(ANALYTICS_DIR.glob("trades_*.json"), reverse=True)[:7]:
            trades = _load_json(f) or []
            if trades:
                pnl = sum(t["net_pnl"] for t in trades)
                wins = sum(1 for t in trades if t["won"])
                weekly.append({"date": f.stem.replace("trades_",""),
                               "trades": len(trades), "wins": wins, "net_pnl": round(pnl,2)})
        ctx["weekly_summary"] = weekly

        # Live portfolio from DB
        if DB_PATH.exists():
            try:
                conn = sqlite3.connect(DB_PATH, timeout=10.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                conn.row_factory = sqlite3.Row
                ctx["capital"] = float(
                    (conn.execute("SELECT value FROM meta WHERE key='capital'").fetchone() or [100000])[0]
                )
                ctx["open_positions"] = [dict(r) for r in
                    conn.execute("SELECT * FROM positions ORDER BY entry_time DESC").fetchall()]
                ctx["recent_trades"] = [dict(r) for r in
                    conn.execute("SELECT * FROM trades ORDER BY exit_time DESC LIMIT 10").fetchall()]
                conn.close()
            except Exception:
                pass

        # Recent log file excerpt
        log_excerpt = []
        log_dir = Path("logs")
        log_files = sorted(log_dir.glob("nexus_trader_*.log"), reverse=True)
        if log_files:
            try:
                lines = log_files[0].read_text(encoding="utf-8", errors="replace").splitlines()
                log_excerpt = lines[-max_log_lines:]
            except Exception:
                pass
        ctx["log_excerpt"] = log_excerpt

        # Decision log excerpt
        dec_dir = Path("logs/decisions")
        today_dash = _now_ist().strftime("%Y-%m-%d")
        dec_files = sorted(dec_dir.glob(f"decisions_{today_dash}*.log"), reverse=True) if dec_dir.exists() else []
        if dec_files:
            try:
                decisions = _load_json(dec_files[0]) or []
                ctx["recent_decisions"] = decisions[-20:] if isinstance(decisions, list) else []
            except Exception:
                ctx["recent_decisions"] = []
        else:
            ctx["recent_decisions"] = []

        return ctx

    def get_log_tail(self, n: int = 100) -> str:
        """Return last n lines of today's log file as a single string."""
        log_dir = Path("logs")
        log_files = sorted(log_dir.glob("nexus_trader_*.log"), reverse=True)
        if not log_files:
            return "No log files found."
        try:
            lines = log_files[0].read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except Exception as e:
            return f"Could not read log: {e}"


# Module-level singleton
analytics = AnalyticsLogger()
