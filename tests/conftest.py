import os
import sys
from unittest.mock import MagicMock

# Mock aiohttp and mcp to prevent imports of uvicorn/aiohttp from hanging during tests on Windows
class MockModule(MagicMock):
    pass

sys.modules['aiohttp'] = MockModule()
sys.modules['aiohttp.client'] = MockModule()
sys.modules['aiohttp.client_exceptions'] = MockModule()
sys.modules['aiohttp.log'] = MockModule()
sys.modules['aiohttp.typedefs'] = MockModule()
sys.modules['aiohttp.http_exceptions'] = MockModule()
sys.modules['mcp'] = MockModule()
sys.modules['mcp.types'] = MockModule()

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Ensure fake API keys are present before any module-level Config() runs.
# Uses setdefault so real keys in .env take precedence when running live.
# ---------------------------------------------------------------------------
os.environ.setdefault("GEMINI_API_KEY", "fake-gemini")
os.environ.setdefault("GROQ_API_KEY", "fake-groq")
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-anthropic")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "fake-chat")

from data.market_data import MarketDataFetcher  # noqa: E402 — after env vars

# Import shared helpers so test files can use them, and expose as fixtures.
from tests.helpers import make_candles, make_entry, mock_portfolio_factory  # noqa: F401


# ---------------------------------------------------------------------------
# Pytest fixtures wrapping the helper functions
# ---------------------------------------------------------------------------

@pytest.fixture
def make_candles_fixture():
    """Fixture that returns the make_candles helper function."""
    return make_candles


@pytest.fixture(scope="module")
def fetcher():
    """Shared MarketDataFetcher instance for integration tests."""
    return MarketDataFetcher()


@pytest.fixture
def sample_ohlcv():
    """
    Deterministic OHLCV DataFrame for indicator unit tests.
    30 rows, 5-min candles, session-aligned at 09:15 IST.
    No network calls required.
    """
    n = 30
    np.random.seed(42)
    base = 2500.0
    closes = base + np.cumsum(np.random.randn(n) * 10)
    highs = closes + np.random.uniform(5, 20, n)
    lows = closes - np.random.uniform(5, 20, n)
    opens = closes + np.random.randn(n) * 5
    volumes = np.random.randint(10_000, 200_000, n).astype(float)

    index = pd.date_range("2026-06-06 09:15", periods=n, freq="5min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=index,
    )
