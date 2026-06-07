"""
tests/helpers.py — Shared test helper functions for nexus_trader unit tests.

Import from here in test files:
    from tests.helpers import make_candles, make_entry, mock_portfolio_factory

conftest.py also imports from here to expose the same helpers as pytest fixtures.
"""
import datetime
import os

# Ensure fake API keys are set before any module that imports config runs.
# This file may be imported before conftest.py sets them, so we set them here too.
os.environ.setdefault("GEMINI_API_KEY", "fake-gemini")
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-anthropic")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "fake-chat")

import pandas as pd
import pytz
from unittest.mock import MagicMock

from agents.models import WatchlistEntry

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Candle builder
# ---------------------------------------------------------------------------

def make_candles(prices: list, start_hour: int = 9, start_min: int = 15) -> pd.DataFrame:
    """
    Build a 5-minute IST-aware OHLCV DataFrame from a list of close prices.

    Each row: Open=Close=AdjClose=price, High=price+2, Low=price-2, Volume=500_000.
    Index timestamps start at start_hour:start_min IST, stepped by 5 minutes.
    """
    base = datetime.datetime.now(IST).replace(
        hour=start_hour, minute=start_min, second=0, microsecond=0
    )
    rows = [
        {
            "Open": p,
            "High": p + 2,
            "Low": p - 2,
            "Close": p,
            "Adj Close": p,
            "Volume": 500_000,
        }
        for p in prices
    ]
    index = [base + datetime.timedelta(minutes=5 * i) for i in range(len(prices))]
    return pd.DataFrame(rows, index=index)


# ---------------------------------------------------------------------------
# WatchlistEntry builder
# ---------------------------------------------------------------------------

def make_entry(
    symbol: str,
    strategy: str,
    entry_trigger: float,
    stop_loss: float,
    target: float,
    atr: float = 10.0,
) -> WatchlistEntry:
    """Return a minimal WatchlistEntry suitable for unit tests."""
    return WatchlistEntry(
        symbol=symbol,
        sector="Test",
        gap_pct=2.0,
        gap_score=3.0,
        strategy=strategy,
        entry_trigger=entry_trigger,
        stop_loss=stop_loss,
        target=target,
        rr_ratio=1.5,
        catalyst_type="EARNINGS",
        atr=atr,
    )


# ---------------------------------------------------------------------------
# Mock portfolio factory
# ---------------------------------------------------------------------------

def mock_portfolio_factory(positions=None) -> MagicMock:
    """
    Return a MagicMock that mimics PaperPortfolio.

    get_portfolio_summary() returns a dict whose 'positions' list is provided
    by the caller.  buy/sell/partial_exit/update_stop_loss all return True.
    """
    p = MagicMock()
    p.get_portfolio_summary.return_value = {
        "capital": 100_000.0,
        "positions": positions or [],
        "daily_pnl": 0.0,
        "is_halted": False,
        "trade_count": 0,
    }
    p.buy.return_value = True
    p.sell.return_value = True
    p.partial_exit.return_value = True
    p.update_stop_loss.return_value = True
    return p
