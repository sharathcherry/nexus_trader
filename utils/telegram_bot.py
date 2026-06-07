"""
utils/telegram_bot.py — Telegram chatbot for nexus_trader

Polls Telegram for incoming commands and replies with live trading data
read directly from portfolio.db and review JSONs. Runs in a daemon thread
so it never blocks the trading loop.

Supported commands:
    /status     — Capital, daily P&L, open positions count, trade count
    /positions  — All open positions with entry / SL / target
    /trades     — Today's completed trades with P&L per trade
    /summary    — Latest Claude Sonnet end-of-day review
    /help       — Command list

Security: Only responds to messages from the configured TELEGRAM_CHAT_ID.
          Auto-disables if token/chat_id are missing or placeholder values.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import requests

_DB_PATH = Path("execution/portfolio.db")
_REVIEW_DIR = Path("logs/performance")

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
        self._token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
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

        if cmd in handlers:
            reply = handlers[cmd]()
        elif cmd.startswith("/"):
            reply = "❓ Unknown command. Use /help to see available commands."
        else:
            return  # ignore non-command messages

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
            rows = conn.execute(
                "SELECT * FROM trades "
                "WHERE date(exit_time) = date('now', 'localtime') "
                "ORDER BY exit_time DESC LIMIT 15"
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
        if not _REVIEW_DIR.exists():
            return "📭 No review data available. Runs after market close (15:35 IST)."

        files = sorted(_REVIEW_DIR.glob("review_*.json"), reverse=True)
        # Skip partial/failed reviews
        valid = [
            f for f in files
            if "partial" not in f.name and "failed" not in f.name
        ]
        if not valid:
            return "📭 No completed review found. Check back after 15:35 IST."

        try:
            with open(valid[0]) as fh:
                data = json.load(fh)

            trades = data.get("trades", [])
            wins = sum(1 for t in trades if t.get("net_pnl", 0) > 0)
            total_pnl = sum(t.get("net_pnl", 0) for t in trades)
            win_rate = (wins / len(trades) * 100) if trades else 0.0

            assessment = data.get("assessment", "—")
            recs = data.get("recommendations", [])
            rec_text = (
                "\n".join(f"  • {r}" for r in recs[:4])
                if recs else "  None"
            )

            date_str = valid[0].stem.replace("review_", "")
            pnl_emoji = "📗" if total_pnl >= 0 else "📕"

            return (
                f"<b>{pnl_emoji} Daily Summary — {date_str}</b>\n\n"
                f"Trades: {len(trades)}  |  Wins: {wins}  "
                f"|  Win Rate: {win_rate:.0f}%\n"
                f"Net P&L: <b>₹{total_pnl:+,.2f}</b>\n\n"
                f"<b>Claude's Assessment:</b>\n{assessment}\n\n"
                f"<b>Recommendations:</b>\n{rec_text}"
            )
        except Exception as exc:
            return f"⚠️ Error reading review: {exc}"

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


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

bot = TelegramCommandBot()
