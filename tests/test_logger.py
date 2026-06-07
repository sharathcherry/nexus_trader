"""
tests/test_logger.py — Tests for custom log levels in utils/logger.py

conftest.py sets fake env vars before any module is imported.
"""

import logging

import pytest


def test_custom_log_levels_registered():
    """TRADE, PNL_PROFIT, PNL_LOSS levels must be registered in logging module."""
    import utils.logger  # trigger level registration (idempotent)
    assert logging.getLevelName(25) == "TRADE"
    assert logging.getLevelName(26) == "PNL_PROFIT"
    assert logging.getLevelName(27) == "PNL_LOSS"


def test_logger_has_custom_methods():
    """Logger instances must have .trade(), .pnl_profit(), .pnl_loss() bound methods."""
    from utils.logger import setup_logger
    logger = setup_logger("test_custom_levels")
    assert hasattr(logger, "trade"), "Logger missing .trade() method"
    assert hasattr(logger, "pnl_profit"), "Logger missing .pnl_profit() method"
    assert hasattr(logger, "pnl_loss"), "Logger missing .pnl_loss() method"
    assert callable(logger.trade)
    assert callable(logger.pnl_profit)
    assert callable(logger.pnl_loss)
