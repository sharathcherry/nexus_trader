"""
tests/test_scheduler.py — Tests for TradingScheduler

conftest.py sets fake env vars before any module is imported.
"""

from unittest.mock import MagicMock

import pytest


def _make_scheduler():
    """Return a TradingScheduler with a mocked NexusTrader (no real portfolio)."""
    from execution.scheduler import TradingScheduler
    trader = MagicMock()
    return TradingScheduler(nexus_trader=trader)


def test_scheduler_executor_type():
    """Scheduler must use a ThreadPoolExecutor (not blocking or async)."""
    sched = _make_scheduler()
    executors = sched._scheduler._executors
    assert "default" in executors
    # APScheduler wraps the executor — check the class name
    executor_obj = executors["default"]
    assert "ThreadPool" in type(executor_obj).__name__


def test_scheduler_job_ids():
    """pre_market, market_session, and post_market jobs must be registered."""
    sched = _make_scheduler()
    job_ids = {job.id for job in sched._scheduler.get_jobs()}
    assert "pre_market" in job_ids
    assert "market_session" in job_ids
    assert "post_market" in job_ids
