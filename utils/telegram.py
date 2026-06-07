"""
utils/telegram.py -- Telegram trade notification and chatbot helper for nexus_trader.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytz
import requests
from groq import Groq

from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_DB_PATH = Path("execution/portfolio.db")
_PLACEHOLDER_TOKENS = {"", "fake-token", "your_token_here"}


def _get_conn() -> sqlite3.Connection | None:
    if not _DB_PATH.exists():
        return None
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _meta(conn: sqlite3.Connection, key: str, default: str = "0") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


# ---------------------------------------------------------------------------
# TelegramNotifier -- fire-and-forget trade alerts
# ---------------------------------------------------------------------------

class TelegramNotifier:
    def __init__(self) -> None:
        self._token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
        self._chat_id = getattr(config, "TELEGRAM_CHAT_ID", "")
        self._enabled = bool(
            self._token and self._chat_id
            and self._token not in ("fake-token", "your_token_here", "")
            and self._chat_id not in ("fake-chat", "your_chat_id_here", "")
        )
        if not self._enabled:
            logger.info("TelegramNotifier: disabled (placeholder keys)")

    def _send(self, text: str) -> None:
        if not self._enabled:
            return
        try:
            url = _TELEGRAM_API.format(token=self._token)
            resp = requests.post(url, json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
            if not resp.ok:
                logger.warning("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("Telegram send error (suppressed): %s", exc)

    def send_buy(self, symbol: str, price: float, qty: int, strategy: str, sl: float, target: float) -> None:
        now = datetime.now(IST).strftime("%H:%M IST")
        rr = round((target - price) / (price - sl), 2) if price > sl else 0
        self._send(
            f"<b>BUY {symbol}</b>\n"
            f"Strategy : {strategy}\n"
            f"Price    : Rs{price:,.2f}  x{qty}\n"
            f"SL       : Rs{sl:,.2f}\n"
            f"Target   : Rs{target:,.2f}\n"
            f"R:R      : {rr}\n"
            f"Time     : {now}"
        )

    def send_sell(self, symbol: str, price: float, qty: int, reason: str, net_pnl: Optional[float] = None) -> None:
        now = datetime.now(IST).strftime("%H:%M IST")
        emoji = "STOP" if reason == "SL_HIT" else "TARGET" if reason == "TARGET_HIT" else "EXIT"
        pnl_str = f"\nNet P&L  : Rs{net_pnl:+,.2f}" if net_pnl is not None else ""
        self._send(
            f"<b>{emoji} -- {symbol}</b>\n"
            f"Reason   : {reason}\n"
            f"Price    : Rs{price:,.2f}  x{qty}{pnl_str}\n"
            f"Time     : {now}"
        )

    def send_partial_exit(self, symbol: str, price: float, qty: int) -> None:
        now = datetime.now(IST).strftime("%H:%M IST")
        self._send(f"<b>PARTIAL EXIT -- {symbol}</b>\nPrice : Rs{price:,.2f}  x{qty}\nTime  : {now}")

    def send_squareoff(self, symbol: str, price: float, qty: int) -> None:
        now = datetime.now(IST).strftime("%H:%M IST")
        self._send(f"<b>SQUAREOFF -- {symbol}</b>\nPrice : Rs{price:,.2f}  x{qty}\nTime  : {now}")

    def send_market_open(self, watchlist_count: int, capital: float) -> None:
        now = datetime.now(IST).strftime("%H:%M IST")
        self._send(
            f"<b>nexus_trader -- Market Open</b>\n"
            f"Watchlist : {watchlist_count} stocks\n"
            f"Capital   : Rs{capital:,.0f}\n"
            f"Time      : {now}"
        )

    def send_morning_briefing(self, watchlist: list, bias: str, capital: float) -> None:
        if not watchlist:
            self._send(
                f"<b>nexus_trader -- Morning Briefing</b>\n\n"
                f"Market Bias : {bias}\n"
                f"Setups      : 0 -- no trades today\n"
                f"Capital     : Rs{capital:,.0f}"
            )
            return
        strategy_counts: dict[str, int] = {}
        for e in watchlist:
            s = e.get("strategy") if isinstance(e, dict) else getattr(e, "strategy", "?")
            strategy_counts[s] = strategy_counts.get(s, 0) + 1
        strat_str = "  ".join(f"{k}x{v}" for k, v in strategy_counts.items())
        lines = ""
        for e in watchlist[:3]:
            sym = e.get("symbol") if isinstance(e, dict) else getattr(e, "symbol", "?")
            gap = e.get("gap_pct", 0) if isinstance(e, dict) else getattr(e, "gap_pct", 0)
            strat = e.get("strategy", "?") if isinstance(e, dict) else getattr(e, "strategy", "?")
            lines += f"\n  * {sym}  {gap:+.2f}%  [{strat}]"
        self._send(
            f"<b>nexus_trader -- Morning Briefing</b>\n\n"
            f"Market Bias : {bias}\n"
            f"Setups      : {len(watchlist)} stocks  ({strat_str})\n"
            f"Capital     : Rs{capital:,.0f}\n\n"
            f"<b>Top Picks:</b>{lines}\n\n"
            f"<i>Market opens 09:15 IST -- entries from 09:30</i>"
        )

    def send_daily_summary(self, total_trades: int, wins: int, net_pnl: float, capital: float) -> None:
        losses = total_trades - wins
        win_rate = (wins / total_trades * 100) if total_trades else 0
        emoji = "PROFIT" if net_pnl >= 0 else "LOSS"
        self._send(
            f"<b>nexus_trader -- Daily Summary ({emoji})</b>\n"
            f"Trades   : {total_trades}  (W:{wins} L:{losses})\n"
            f"Win Rate : {win_rate:.0f}%\n"
            f"Net P&L  : Rs{net_pnl:+,.2f}\n"
            f"Capital  : Rs{capital:,.0f}"
        )

    def send_halted(self, daily_pnl: float, limit_pct: float) -> None:
        self._send(
            f"<b>TRADING HALTED -- Daily loss limit hit</b>\n"
            f"Daily P&L : Rs{daily_pnl:+,.2f}\n"
            f"Limit     : {limit_pct:.0%}"
        )

    def send_error(self, context: str, error: str) -> None:
        self._send(f"<b>nexus_trader -- Error</b>\nContext : {context}\nError   : {str(error)[:300]}")


# ---------------------------------------------------------------------------
# TelegramCommandBot -- long-poll chatbot responding to user commands
# ---------------------------------------------------------------------------

class TelegramCommandBot:
    def __init__(self) -> None:
        self._token: str = getattr(config, "TELEGRAM_BOT_TOKEN", "")
        self._chat_id: str = getattr(config, "TELEGRAM_CHAT_ID", "")
        self._enabled: bool = bool(self._token and self._chat_id and self._token not in _PLACEHOLDER_TOKENS)
        self._offset: int = 0
        self._thread: threading.Thread | None = None
        self._running: bool = False

    def start(self) -> None:
        if not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, name="telegram-bot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    try:
                        self._handle_update(update)
                    except Exception:
                        pass
                    self._offset = update["update_id"] + 1
            except Exception:
                pass
            time.sleep(2)

    def _get_updates(self) -> list[dict]:
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        resp = requests.get(url, params={"offset": self._offset, "timeout": 10}, timeout=15)
        return resp.json().get("result", [])

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(self._chat_id):
            return

        cmd = text.split()[0].lower() if text else ""
        handlers = {
            "/status":    self._status_message,
            "/positions": self._positions_message,
            "/trades":    self._trades_message,
            "/watchlist": self._watchlist_message,
            "/weekly":    self._weekly_message,
            "/strategy":  self._strategy_message,
            "/summary":   self._summary_message,
            "/help":      self._help_message,
        }

        if cmd and not cmd.startswith("/") and f"/{cmd}" in handlers:
            cmd = f"/{cmd}"

        if cmd in handlers:
            reply = handlers[cmd]()
        elif cmd.startswith("/"):
            reply = "Unknown command. Use /help to see available commands."
        elif cmd in ("hi", "hello", "hey"):
            reply = f"Hello! I am the nexus_trader bot.\n\n{self._help_message()}"
        else:
            reply = self._groq_chat(text)
        self._send(reply)

    def _groq_chat(self, user_msg: str) -> str:
        """Answer any free-form question using Groq + live portfolio context."""
        try:
            from utils.analytics_logger import analytics
            ctx = analytics.get_context_for_ai(max_log_lines=50)
        except Exception:
            ctx = {}

        # Compact context for system prompt
        capital     = ctx.get("capital", "unknown")
        positions   = ctx.get("open_positions", [])
        recent      = ctx.get("recent_trades", [])
        stats       = ctx.get("analytics", {})
        today_sess  = ctx.get("today_session", {})
        weekly      = ctx.get("weekly_summary", [])
        log_excerpt = "\n".join(ctx.get("log_excerpt", [])[-30:])
        decisions   = ctx.get("recent_decisions", [])

        def fmt_positions(p):
            if not p: return "None"
            return "\n".join(
                f"  {x['symbol']} {x.get('strategy','')} entry=Rs{x['entry_price']:.2f} "
                f"sl=Rs{x.get('stop_loss',0):.2f} target=Rs{x.get('target',0):.2f} qty={x['qty']}"
                for x in p
            )

        def fmt_trades(t):
            if not t: return "None"
            return "\n".join(
                f"  {x['symbol']} {x.get('strategy','')} PnL=Rs{x['net_pnl']:+.2f} "
                f"exit={x.get('exit_reason','')} @ {x['exit_time'][:16]}"
                for x in t[:8]
            )

        system = f"""You are nexus_trader's AI trading assistant embedded in a Telegram bot.
Answer questions about portfolio performance, trades, logs, and strategy.
Be concise (max 5-6 lines), factual, and use Rs for Indian Rupees.

LIVE PORTFOLIO DATA:
Capital: Rs{capital}
Open positions ({len(positions)}):
{fmt_positions(positions)}

Recent trades:
{fmt_trades(recent)}

All-time stats: {stats.get('total_trades',0)} trades, {stats.get('winners',0)}W/{stats.get('losers',0)}L, net PnL=Rs{stats.get('total_net_pnl',0):+.2f}, avg RR={stats.get('avg_realized_rr',0):.2f}
Best trade: {stats.get('best_trade')}
Worst trade: {stats.get('worst_trade')}

Today session: {today_sess}
Weekly summary: {weekly}

RECENT LOG (last 30 lines):
{log_excerpt}

Recent decisions: {decisions[-5:] if decisions else 'none'}

If the user asks to analyse logs, reference the log excerpt above. If data is missing, say so honestly."""

        try:
            groq_key = getattr(config, "GROQ_API_KEY", "")
            if not groq_key:
                return "Groq API key not configured. Check your .env file."
            client = Groq(api_key=groq_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_msg},
                ],
                max_tokens=400,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            return f"AI error: {e}"

    def _send(self, text: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            requests.post(url, json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        except Exception:
            pass

    def _status_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "Portfolio database not found. Has the system run today?"
        try:
            capital = float(_meta(conn, "capital", "100000"))
            daily_pnl = float(_meta(conn, "daily_pnl", "0"))
            trade_count = int(_meta(conn, "trade_count", "0"))
            is_halted = _meta(conn, "is_halted", "0") == "1"
            pos_count = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            halt_line = "\nTRADING HALTED -- daily loss limit hit." if is_halted else ""
            return (
                f"<b>nexus_trader Status</b>{halt_line}\n\n"
                f"Capital         : Rs{capital:,.2f}\n"
                f"Daily P&L       : Rs{daily_pnl:+,.2f}\n"
                f"Open Positions  : {pos_count}\n"
                f"Trades Today    : {trade_count}"
            )
        finally:
            conn.close()

    def _positions_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "Portfolio database not found."
        try:
            rows = conn.execute("SELECT * FROM positions ORDER BY entry_time DESC").fetchall()
            if not rows:
                return "No open positions right now."
            lines = ["<b>Open Positions</b>\n"]
            for r in rows:
                lines.append(
                    f"<b>{r['symbol']}</b>  [{r['strategy']}]\n"
                    f"   Entry: Rs{r['entry_price']:.2f}  x{r['qty']}\n"
                    f"   SL: Rs{r['stop_loss']:.2f}  Target: Rs{r['target']:.2f}"
                )
            return "\n\n".join(lines)
        finally:
            conn.close()

    def _trades_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "Portfolio database not found."
        try:
            today_ist = datetime.now(IST).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT * FROM trades WHERE date(exit_time) = ? ORDER BY exit_time DESC LIMIT 15",
                (today_ist,)
            ).fetchall()
            if not rows:
                return "No completed trades today yet."
            total_pnl = sum(r["net_pnl"] for r in rows)
            wins = sum(1 for r in rows if r["net_pnl"] > 0)
            lines = [f"<b>Today's Trades</b>  ({wins}W/{len(rows)-wins}L  |  Rs{total_pnl:+,.2f} net)\n"]
            for r in rows:
                tag = "WIN" if r["net_pnl"] > 0 else "LOSS"
                lines.append(
                    f"[{tag}] <b>{r['symbol']}</b>  {r['exit_reason']}\n"
                    f"   Rs{r['entry_price']:.2f} > Rs{r['exit_price']:.2f}  x{r['qty']}  |  <b>Rs{r['net_pnl']:+,.2f}</b>"
                )
            return "\n\n".join(lines)
        finally:
            conn.close()

    def _watchlist_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "Portfolio database not found."
        try:
            rows = conn.execute("SELECT * FROM watchlist ORDER BY gap_pct DESC").fetchall()
            if not rows:
                return "No watchlist for today yet. Runs at 08:30 IST."
            lines = ["<b>Today's Watchlist</b>\n"]
            for r in rows:
                lines.append(
                    f"<b>{r['symbol']}</b>  [{r['strategy']}]\n"
                    f"   Gap: {r['gap_pct']:+.2f}%  R:R: {r['rr_ratio']:.2f}\n"
                    f"   Entry: Rs{r['entry_trigger']:.2f}  SL: Rs{r['stop_loss']:.2f}  T: Rs{r['target']:.2f}"
                )
            return "\n\n".join(lines)
        finally:
            conn.close()

    def _weekly_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "Portfolio database not found."
        try:
            rows = conn.execute(
                """SELECT DATE(exit_time) as day, COUNT(*) as trades,
                          SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
                          ROUND(SUM(net_pnl), 2) as net_pnl
                   FROM trades WHERE DATE(exit_time) >= DATE('now', '-7 days')
                   GROUP BY day ORDER BY day DESC"""
            ).fetchall()
            if not rows:
                return "No trades in the last 7 days."
            total_pnl = sum(r["net_pnl"] for r in rows)
            lines = [f"<b>Weekly P&L (last 7 days)</b>\n"]
            for r in rows:
                wr = int(r["wins"] / r["trades"] * 100) if r["trades"] else 0
                tag = "UP" if r["net_pnl"] >= 0 else "DN"
                lines.append(f"[{tag}] <b>{r['day']}</b>  {r['trades']} trades  {wr}% WR  |  <b>Rs{r['net_pnl']:+,.2f}</b>")
            lines.append(f"\n<b>Total: Rs{total_pnl:+,.2f}</b>")
            return "\n".join(lines)
        finally:
            conn.close()

    def _strategy_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "Portfolio database not found."
        try:
            rows = conn.execute(
                """SELECT strategy, COUNT(*) as total,
                          SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as wins,
                          ROUND(SUM(net_pnl), 2) as net_pnl,
                          ROUND(AVG(net_pnl), 2) as avg_pnl
                   FROM trades GROUP BY strategy ORDER BY net_pnl DESC"""
            ).fetchall()
            if not rows:
                return "No trade history yet."
            lines = ["<b>Strategy Performance</b>\n"]
            for r in rows:
                losses = r["total"] - r["wins"]
                wr = int(r["wins"] / r["total"] * 100) if r["total"] else 0
                tag = "UP" if r["net_pnl"] >= 0 else "DN"
                lines.append(
                    f"[{tag}] <b>{r['strategy']}</b>  {r['wins']}W/{losses}L  {wr}% WR\n"
                    f"   Net: Rs{r['net_pnl']:+,.2f}  Avg: Rs{r['avg_pnl']:+,.2f}"
                )
            return "\n\n".join(lines)
        finally:
            conn.close()

    def _summary_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "Portfolio database not found."
        try:
            row = conn.execute("SELECT * FROM daily_reviews ORDER BY review_date DESC LIMIT 1").fetchone()
            if not row:
                return "No completed review found. Check back after 15:35 IST."
            date_str = row["review_date"]
            verdict = row["session_verdict"]
            summary = row["summary"]
            adjustments = json.loads(row["parameter_adjustments"])
            tomorrow_watch = json.loads(row["tomorrow_watch"])
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            trades_rows = conn.execute(
                "SELECT net_pnl FROM trades WHERE date(exit_time) = ?", (formatted_date,)
            ).fetchall()
            total_pnl = sum(t["net_pnl"] for t in trades_rows)
            wins = sum(1 for t in trades_rows if t["net_pnl"] > 0)
            trade_count = len(trades_rows)
            wr = (wins / trade_count * 100) if trade_count else 0
            rec_text = "\n".join(
                f"  * {a['param_name']}: {a['current_value']} > {a['suggested_value']} ({a['reason']})"
                for a in adjustments[:4]
            ) or "  None"
            watch_text = ", ".join(tomorrow_watch) if tomorrow_watch else "None"
            tag = "PROFIT" if total_pnl >= 0 else "LOSS"
            return (
                f"<b>Daily Summary [{tag}] -- {date_str}</b>\n\n"
                f"Trades: {trade_count}  Wins: {wins}  WR: {wr:.0f}%\n"
                f"Net P&L: <b>Rs{total_pnl:+,.2f}</b>\n\n"
                f"<b>Verdict:</b> {verdict}\n\n"
                f"<b>Summary:</b>\n{summary}\n\n"
                f"<b>Watch Tomorrow:</b> {watch_text}\n\n"
                f"<b>Recommendations:</b>\n{rec_text}"
            )
        except Exception as exc:
            return f"Error reading review: {exc}"
        finally:
            conn.close()

    def _help_message(self) -> str:
        return (
            "<b>nexus_trader Bot -- Commands</b>\n\n"
            "/status     -- Capital, P&L, positions, halt state\n"
            "/positions  -- All open positions with SL and target\n"
            "/trades     -- Today's completed trades with P&L\n"
            "/watchlist  -- Today's pre-market watchlist\n"
            "/weekly     -- Last 7 days P&L breakdown\n"
            "/strategy   -- Win rate per strategy (all time)\n"
            "/summary    -- Latest AI end-of-day review\n"
            "/help       -- This message\n\n"
            "<i>Data is read live from the portfolio database.</i>"
        )


# Module-level singletons
notifier = TelegramNotifier()
bot = TelegramCommandBot()
