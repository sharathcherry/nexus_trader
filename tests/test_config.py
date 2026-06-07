"""
tests/test_config.py — Tests for Config.is_trading_day()
"""

from datetime import date

import pytest

# conftest.py sets fake env vars before this module is imported


def test_is_trading_day_nse_holiday():
    """Republic Day 2026 is an NSE holiday — should NOT be a trading day."""
    from config import config
    assert config.is_trading_day(date(2026, 1, 26)) is False


def test_is_trading_day_weekend():
    """Saturday 2026-06-06 should NOT be a trading day."""
    from config import config
    d = date(2026, 6, 6)
    assert d.weekday() == 5  # Saturday
    assert config.is_trading_day(d) is False


def test_is_trading_day_normal_weekday():
    """Monday 2026-06-08 is not a holiday — should be a trading day."""
    from config import config
    d = date(2026, 6, 8)
    assert d.weekday() == 0  # Monday
    assert config.is_trading_day(d) is True
