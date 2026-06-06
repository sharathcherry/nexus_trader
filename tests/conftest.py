import pytest
import pandas as pd
import numpy as np
from data.market_data import MarketDataFetcher


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
