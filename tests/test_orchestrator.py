"""
tests/test_orchestrator.py — Tests for NexusTrader orchestrator

conftest.py sets fake env vars before any module is imported.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def test_nexus_trader_init():
    """NexusTrader should initialize with an empty watchlist and event unset."""
    with (
        patch("execution.scheduler.PaperPortfolio", return_value=MagicMock()),
        patch("execution.scheduler.OrderManager", return_value=MagicMock()),
    ):
        from execution.scheduler import NexusTrader
        trader = NexusTrader(dry_run=False)

    assert trader._watchlist == []
    assert not trader._watchlist_ready.is_set()
    assert trader.dry_run is False


def test_nexus_trader_pre_market_holiday_guard():
    """
    run_pre_market_pipeline() on an NSE holiday should skip the pipeline
    and set watchlist_ready immediately with an empty watchlist.
    """
    with (
        patch("execution.scheduler.PaperPortfolio", return_value=MagicMock()),
        patch("execution.scheduler.OrderManager", return_value=MagicMock()),
    ):
        from execution.scheduler import NexusTrader
        trader = NexusTrader(dry_run=False)
        trader.run_pre_market_pipeline(date_override=date(2026, 1, 26))  # Republic Day

    assert trader._watchlist == []
    assert trader._watchlist_ready.is_set()


def test_nexus_trader_pre_market_no_candidates(monkeypatch):
    """
    When AgentI1 returns no candidates, watchlist stays empty and event is set.
    """
    from agents.models import MarketBias

    async def fake_i0():
        return MarketBias(
            bias="NEUTRAL",
            bias_strength=0.5,
            gift_nifty_gap_pct=0.0,
            valid_strategies=["GAP_AND_GO"],
            confidence=0.6,
        )

    async def fake_i1():
        return []  # no candidates

    with (
        patch("execution.scheduler.PaperPortfolio", return_value=MagicMock()),
        patch("execution.scheduler.OrderManager", return_value=MagicMock()),
    ):
        import execution.scheduler as sched_mod
        monkeypatch.setattr(sched_mod.agent_i0, "run", fake_i0)
        monkeypatch.setattr(sched_mod.agent_i1, "run", fake_i1)

        from execution.scheduler import NexusTrader
        trader = NexusTrader(dry_run=False)
        trader.run_pre_market_pipeline(date_override=date(2026, 6, 8))  # normal weekday

    assert trader._watchlist == []
    assert trader._watchlist_ready.is_set()
