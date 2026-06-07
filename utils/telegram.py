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


# Module-level singleton — import this everywhere
notifier = TelegramNotifier()
