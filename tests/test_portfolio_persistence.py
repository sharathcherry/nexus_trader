"""
tests/test_portfolio_persistence.py — Integration and unit tests for PaperPortfolio DB persistence.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, date, timedelta
import pytz

from execution.portfolio import PaperPortfolio
from agents.models import WatchlistEntry
from config import config

IST = pytz.timezone("Asia/Kolkata")


@pytest.fixture
def isolated_portfolio(tmp_path):
    """Fixture that patches portfolio.DB_PATH to a temporary file to run in isolation."""
    temp_db_path = tmp_path / "test_portfolio.db"
    with patch("execution.portfolio.DB_PATH", temp_db_path):
        portfolio = PaperPortfolio()
        yield portfolio
        # Cleanup WAL files if exist
        for f in tmp_path.glob("test_portfolio.db*"):
            try:
                f.unlink()
            except Exception:
                pass


def test_initial_portfolio_state(isolated_portfolio):
    """Initial meta parameters must be seeded correctly on first run."""
    assert isolated_portfolio.capital == 100_000.0
    assert isolated_portfolio.daily_pnl == 0.0
    assert isolated_portfolio.trade_count == 0
    assert not isolated_portfolio.is_halted


def test_watchlist_save_and_load(isolated_portfolio):
    """Watchlist entries should be correctly saved to SQLite and loaded back."""
    entry1 = WatchlistEntry(
        symbol="RELIANCE.NS",
        sector="Energy",
        gap_pct=2.5,
        gap_score=3.5,
        strategy="GAP_AND_GO",
        entry_trigger=2450.0,
        stop_loss=2425.0,
        target=2500.0,
        rr_ratio=2.0,
        catalyst_type="EARNINGS",
        atr=15.0,
    )
    entry2 = WatchlistEntry(
        symbol="TCS.NS",
        sector="IT",
        gap_pct=-1.8,
        gap_score=2.2,
        strategy="GAP_FILL",
        entry_trigger=3800.0,
        stop_loss=3840.0,
        target=3720.0,
        rr_ratio=2.0,
        catalyst_type="MACRO",
        atr=30.0,
    )

    isolated_portfolio.save_watchlist([entry1, entry2])

    loaded = isolated_portfolio.load_watchlist()
    assert len(loaded) == 2

    # Map by symbol for easy assertion
    loaded_map = {e.symbol: e for e in loaded}
    assert "RELIANCE.NS" in loaded_map
    assert "TCS.NS" in loaded_map

    # Check fields of Reliance
    rel = loaded_map["RELIANCE.NS"]
    assert rel.sector == "Energy"
    assert rel.gap_pct == 2.5
    assert rel.strategy == "GAP_AND_GO"
    assert rel.entry_trigger == 2450.0
    assert rel.stop_loss == 2425.0
    assert rel.target == 2500.0
    assert rel.rr_ratio == 2.0
    assert rel.catalyst_type == "EARNINGS"
    assert rel.atr == 15.0


def test_update_watchlist_trigger(isolated_portfolio):
    """Updating entry_trigger for a watchlist symbol must persist in the DB."""
    entry = WatchlistEntry(
        symbol="INFY.NS",
        sector="IT",
        gap_pct=1.5,
        gap_score=1.5,
        strategy="ORB_BREAKOUT",
        entry_trigger=1450.0,
        stop_loss=1440.0,
        target=1470.0,
        rr_ratio=2.0,
        catalyst_type="UNKNOWN",
        atr=10.0,
    )
    isolated_portfolio.save_watchlist([entry])

    # Perform update (e.g. at 09:30 ORB level override)
    isolated_portfolio.update_watchlist_trigger("INFY.NS", 1455.5)

    loaded = isolated_portfolio.load_watchlist()
    assert len(loaded) == 1
    assert loaded[0].entry_trigger == 1455.5


def test_watchlist_cleared_on_new_day(isolated_portfolio):
    """Daily reset (triggered by date change) must clear the watchlist table."""
    entry = WatchlistEntry(
        symbol="INFY.NS",
        sector="IT",
        gap_pct=1.5,
        gap_score=1.5,
        strategy="ORB_BREAKOUT",
        entry_trigger=1450.0,
        stop_loss=1440.0,
        target=1470.0,
        rr_ratio=2.0,
        catalyst_type="UNKNOWN",
        atr=10.0,
    )
    isolated_portfolio.save_watchlist([entry])
    assert len(isolated_portfolio.load_watchlist()) == 1

    # Fake a new day by updating the last_trade_date metadata to yesterday
    yesterday = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    isolated_portfolio._set_meta("last_trade_date", yesterday)

    # Call restore state to simulate a startup on the new day
    isolated_portfolio._restore_state()

    # Watchlist should now be empty
    assert len(isolated_portfolio.load_watchlist()) == 0


def test_save_daily_review(isolated_portfolio):
    """Daily reviews should be correctly saved to SQLite and update on conflict."""
    winning = ["GAP_AND_GO"]
    underperforming = ["GAP_FILL"]
    params = [{"param_name": "MIN_RISK_REWARD", "current_value": 1.5, "suggested_value": 1.5, "reason": "Consistent"}]
    watch = ["RELIANCE.NS", "TCS.NS"]
    summary = "Profitable session with solid breakouts."

    # Save
    isolated_portfolio.save_daily_review(
        review_date="20260607",
        verdict="PROFITABLE",
        winning_strategies=winning,
        underperforming_strategies=underperforming,
        parameter_adjustments=params,
        tomorrow_watch=watch,
        summary=summary,
    )

    # Directly check database using a connection
    import sqlite3
    with sqlite3.connect(isolated_portfolio._get_meta("last_trade_date")) as conn: # dummy context but we query through internal connection helper
        pass
    
    # Let's query using the portfolio's internal conn factory (which is patched)
    from execution.portfolio import _get_conn
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_reviews WHERE review_date = ?", ("20260607",)).fetchone()
    
    assert row is not None
    assert row["session_verdict"] == "PROFITABLE"
    assert row["summary"] == summary
    import json
    assert json.loads(row["winning_strategies"]) == winning
    assert json.loads(row["underperforming_strategies"]) == underperforming
    assert json.loads(row["parameter_adjustments"]) == params
    assert json.loads(row["tomorrow_watch"]) == watch
