"""
utils/telegram.py — Telegram trade notification helper.

Sends formatted messages to a Telegram chat via the Bot API.
All methods are fire-and-forget: failures are logged as warnings,
never raised — the trading loop must not crash due to a notification failure.

Usage:
    from utils.telegram import notifier
    notifier.send_buy("RELIANCE.NS", 1480.0, qty=5, strategy="GAP_AND_GO",
                      sl=1465.0, target=1510.0)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
import sqlite3
import threading
import time
from pathlib import Path

import pytz
import requests

from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """
    Thin wrapper around the Telegram Bot API.

    Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from config.
    Silently disabled if either key is a placeholder/empty.
    """

    def __init__(self) -> None:
        self._token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
        self._chat_id = getattr(config, "TELEGRAM_CHAT_ID", "")
        self._enabled = bool(
            self._token
            and self._chat_id
            and self._token not in ("fake-token", "your_token_here", "")
            and self._chat_id not in ("fake-chat", "your_chat_id_here", "")
        )
        if not self._enabled:
            logger.info("TelegramNotifier: disabled (placeholder keys detected)")

    # ------------------------------------------------------------------
    # Internal sender
    # ------------------------------------------------------------------

    def _send(self, text: str) -> None:
        """POST a message. Swallows all exceptions."""
        if not self._enabled:
            return
        try:
            url = _TELEGRAM_API.format(token=self._token)
            payload = {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
            resp = requests.post(url, json=payload, timeout=10)
            if not resp.ok:
                logger.warning(
                    "Telegram send failed: %s %s", resp.status_code, resp.text[:200]
                )
        except Exception as exc:
            logger.warning("Telegram send error (suppressed): %s", exc)

    # ------------------------------------------------------------------
    # Trade events
    # ------------------------------------------------------------------

    def send_buy(
        self,
        symbol: str,
        price: float,
        qty: int,
        strategy: str,
        sl: float,
        target: float,
    ) -> None:
        """Send a BUY alert."""
        now = datetime.now(IST).strftime("%H:%M IST")
        rr = round((target - price) / (price - sl), 2) if price > sl else 0
        text = (
            f"<b>🟢 BUY — {symbol}</b>\n"
            f"Strategy : {strategy}\n"
            f"Price    : ₹{price:,.2f}  ×{qty}\n"
            f"SL       : ₹{sl:,.2f}\n"
            f"Target   : ₹{target:,.2f}\n"
            f"R:R      : {rr}\n"
            f"Time     : {now}"
        )
        self._send(text)

    def send_sell(
        self,
        symbol: str,
        price: float,
        qty: int,
        reason: str,
        net_pnl: Optional[float] = None,
    ) -> None:
        """Send a SELL / exit alert."""
        now = datetime.now(IST).strftime("%H:%M IST")
        emoji = "🔴" if reason in ("SL_HIT",) else "✅" if reason == "TARGET_HIT" else "⬛"
        pnl_str = f"\nNet P&L  : ₹{net_pnl:+,.2f}" if net_pnl is not None else ""
        text = (
            f"<b>{emoji} EXIT — {symbol}</b>\n"
            f"Reason   : {reason}\n"
            f"Price    : ₹{price:,.2f}  ×{qty}{pnl_str}\n"
            f"Time     : {now}"
        )
        self._send(text)

    def send_partial_exit(
        self, symbol: str, price: float, qty: int
    ) -> None:
        """Send a partial exit alert."""
        now = datetime.now(IST).strftime("%H:%M IST")
        text = (
            f"<b>🔶 PARTIAL EXIT — {symbol}</b>\n"
            f"Price    : ₹{price:,.2f}  ×{qty}\n"
            f"Time     : {now}"
        )
        self._send(text)

    def send_squareoff(self, symbol: str, price: float, qty: int) -> None:
        """Send end-of-day force squareoff alert."""
        now = datetime.now(IST).strftime("%H:%M IST")
        text = (
            f"<b>🔔 SQUAREOFF — {symbol}</b>\n"
            f"Price    : ₹{price:,.2f}  ×{qty}\n"
            f"Time     : {now}"
        )
        self._send(text)

    # ------------------------------------------------------------------
    # Session events
    # ------------------------------------------------------------------

    def send_market_open(self, watchlist_count: int, capital: float) -> None:
        """Send a session-start summary."""
        now = datetime.now(IST).strftime("%H:%M IST")
        text = (
            f"<b>📈 nexus_trader — Market Open</b>\n"
            f"Watchlist : {watchlist_count} stocks\n"
            f"Capital   : ₹{capital:,.0f}\n"
            f"Time      : {now}"
        )
        self._send(text)

    def send_daily_summary(
        self,
        total_trades: int,
        wins: int,
        net_pnl: float,
        capital: float,
    ) -> None:
        """Send end-of-day P&L summary."""
        losses = total_trades - wins
        win_rate = (wins / total_trades * 100) if total_trades else 0
        emoji = "📗" if net_pnl >= 0 else "📕"
        text = (
            f"<b>{emoji} nexus_trader — Daily Summary</b>\n"
            f"Trades    : {total_trades}  (W:{wins} L:{losses})\n"
            f"Win Rate  : {win_rate:.0f}%\n"
            f"Net P&L   : ₹{net_pnl:+,.2f}\n"
            f"Capital   : ₹{capital:,.0f}"
        )
        self._send(text)

    def send_halted(self, daily_pnl: float, limit_pct: float) -> None:
        """Alert when daily loss limit is breached and trading halts."""
        text = (
            f"<b>🚨 TRADING HALTED — Daily loss limit hit</b>\n"
            f"Daily P&L : ₹{daily_pnl:+,.2f}\n"
            f"Limit     : {limit_pct:.0%}"
        )
        self._send(text)

    def send_error(self, context: str, error: str) -> None:
        """Send a non-fatal error alert."""
        text = (
            f"<b>⚠️ nexus_trader — Error</b>\n"
            f"Context : {context}\n"
            f"Error   : {str(error)[:300]}"
        )
        self._send(text)


# Module-level singletons — import these everywhere
notifier = TelegramNotifier()


# ---------------------------------------------------------------------------
# Telegram Chatbot (Consolidated from utils/telegram_bot.py)
# ---------------------------------------------------------------------------

_DB_PATH = Path("execution/portfolio.db")
_PLACEHOLDER_TOKENS = {"", "fake-token", "your_token_here"}

def _get_conn() -> sqlite3.Connection | None:
    if not _DB_PATH.exists():
        return None
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _meta(conn: sqlite3.Connection, key: str, default: str = "0") -> str:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


class TelegramCommandBot:
    """Long-poll Telegram bot that answers trading status queries."""

    def __init__(self) -> None:
        self._token: str = getattr(config, "TELEGRAM_BOT_TOKEN", "")
        self._chat_id: str = getattr(config, "TELEGRAM_CHAT_ID", "")
        self._enabled: bool = bool(
            self._token
            and self._chat_id
            and self._token not in _PLACEHOLDER_TOKENS
        )
        self._offset: int = 0
        self._thread: threading.Thread | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling thread (no-op if disabled)."""
        if not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, name="telegram-bot", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

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
        resp = requests.get(
            url,
            params={"offset": self._offset, "timeout": 10},
            timeout=15,
        )
        return resp.json().get("result", [])

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message", {})
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Only respond to the configured chat
        if chat_id != str(self._chat_id):
            return

        cmd = text.split()[0].lower() if text else ""

        handlers = {
            "/status":    self._status_message,
            "/positions": self._positions_message,
            "/trades":    self._trades_message,
            "/summary":   self._summary_message,
            "/help":      self._help_message,
        }

        # Support commands without the leading slash
        if cmd and not cmd.startswith("/") and f"/{cmd}" in handlers:
            cmd = f"/{cmd}"

        if cmd in handlers:
            reply = handlers[cmd]()
        elif cmd.startswith("/"):
            reply = "❓ Unknown command. Use /help to see available commands."
        elif cmd in ("hi", "hello", "hey"):
            reply = f"👋 Hello! I am the nexus_trader bot. Please use one of my commands:\n\n{self._help_message()}"
        else:
            return  # ignore other non-command messages

        self._send(reply)

    # ------------------------------------------------------------------
    # Telegram API send
    # ------------------------------------------------------------------

    def _send(self, text: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            requests.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _status_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "⚠️ Portfolio database not found. Has the system run today?"

        try:
            capital    = float(_meta(conn, "capital", "100000"))
            daily_pnl  = float(_meta(conn, "daily_pnl", "0"))
            trade_count = int(_meta(conn, "trade_count", "0"))
            is_halted  = _meta(conn, "is_halted", "0") == "1"

            pos_count = conn.execute(
                "SELECT COUNT(*) FROM positions"
            ).fetchone()[0]

            pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
            halt_line = "\n⛔ <b>Trading HALTED</b> — daily loss limit hit." if is_halted else ""

            return (
                f"<b>🤖 nexus_trader Status</b>{halt_line}\n\n"
                f"💰 Capital:         ₹{capital:,.2f}\n"
                f"{pnl_emoji} Daily P&L:     ₹{daily_pnl:+,.2f}\n"
                f"📊 Open Positions:  {pos_count}\n"
                f"🔄 Trades Today:    {trade_count}"
            )
        finally:
            conn.close()

    def _positions_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "⚠️ Portfolio database not found."

        try:
            rows = conn.execute(
                "SELECT * FROM positions ORDER BY entry_time DESC"
            ).fetchall()

            if not rows:
                return "📭 No open positions right now."

            lines = ["<b>📊 Open Positions</b>\n"]
            for r in rows:
                lines.append(
                    f"🔵 <b>{r['symbol']}</b>  [{r['strategy']}]\n"
                    f"   Entry: ₹{r['entry_price']:.2f}  ×{r['qty']}\n"
                    f"   SL: ₹{r['stop_loss']:.2f}  →  Target: ₹{r['target']:.2f}"
                )
            return "\n\n".join(lines)
        finally:
            conn.close()

    def _trades_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "⚠️ Portfolio database not found."

        try:
            import datetime
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            today_ist = datetime.datetime.now(ist).strftime("%Y-%m-%d")

            rows = conn.execute(
                "SELECT * FROM trades "
                "WHERE date(exit_time) = ? "
                "ORDER BY exit_time DESC LIMIT 15",
                (today_ist,)
            ).fetchall()

            if not rows:
                return "📭 No completed trades today yet."

            total_pnl = sum(r["net_pnl"] for r in rows)
            wins = sum(1 for r in rows if r["net_pnl"] > 0)
            lines = [
                f"<b>🔄 Today's Trades</b>  "
                f"({wins}W/{len(rows)-wins}L  |  ₹{total_pnl:+,.2f} net)\n"
            ]
            for r in rows:
                emoji = "✅" if r["net_pnl"] > 0 else "❌"
                lines.append(
                    f"{emoji} <b>{r['symbol']}</b>  {r['exit_reason']}\n"
                    f"   ₹{r['entry_price']:.2f} → ₹{r['exit_price']:.2f}  "
                    f"×{r['qty']}  |  <b>₹{r['net_pnl']:+,.2f}</b>"
                )
            return "\n\n".join(lines)
        finally:
            conn.close()

    def _summary_message(self) -> str:
        conn = _get_conn()
        if conn is None:
            return "⚠️ Portfolio database not found."

        try:
            row = conn.execute(
                "SELECT * FROM daily_reviews ORDER BY review_date DESC LIMIT 1"
            ).fetchone()

            if not row:
                return "📭 No completed review found in database. Check back after 15:35 IST."

            date_str = row["review_date"]
            verdict = row["session_verdict"]
            winning = json.loads(row["winning_strategies"])
            underperforming = json.loads(row["underperforming_strategies"])
            adjustments = json.loads(row["parameter_adjustments"])
            tomorrow_watch = json.loads(row["tomorrow_watch"])
            summary = row["summary"]

            # Convert YYYYMMDD to YYYY-MM-DD for matching trades exit_time
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            
            trades_rows = conn.execute(
                "SELECT net_pnl FROM trades WHERE date(exit_time) = ?",
                (formatted_date,)
            ).fetchall()
            
            total_pnl = sum(t["net_pnl"] for t in trades_rows)
            wins = sum(1 for t in trades_rows if t["net_pnl"] > 0)
            trade_count = len(trades_rows)
            win_rate = (wins / trade_count * 100) if trade_count else 0.0

            pnl_emoji = "📗" if total_pnl >= 0 else "📕"

            rec_text = "\n".join(
                f"  • {adj['param_name']}: {adj['current_value']} → {adj['suggested_value']} ({adj['reason']})"
                for adj in adjustments[:4]
            ) if adjustments else "  None"

            watch_text = ", ".join(tomorrow_watch) if tomorrow_watch else "None"

            return (
                f"<b>{pnl_emoji} Daily Summary — {date_str}</b>\n\n"
                f"Trades: {trade_count}  |  Wins: {wins}  "
                f"|  Win Rate: {win_rate:.0f}%\n"
                f"Net P&L: <b>₹{total_pnl:+,.2f}</b>\n\n"
                f"<b>Verdict:</b> {verdict}\n\n"
                f"<b>Claude's Assessment:</b>\n{summary}\n\n"
                f"<b>Tomorrow's Watchlist:</b>\n{watch_text}\n\n"
                f"<b>Recommendations:</b>\n{rec_text}"
            )
        except Exception as exc:
            return f"⚠️ Error reading review: {exc}"
        finally:
            conn.close()

    def _help_message(self) -> str:
        return (
            "<b>🤖 nexus_trader Bot — Commands</b>\n\n"
            "/status     — Capital, P&L, positions, halt state\n"
            "/positions  — All open positions with SL &amp; target\n"
            "/trades     — Today's completed trades with P&amp;L\n"
            "/summary    — Latest Claude Sonnet end-of-day review\n"
            "/help       — This message\n\n"
            "<i>Data is read live from the portfolio database.</i>"
        )


bot = TelegramCommandBot()
