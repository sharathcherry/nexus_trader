"""
Data layer tests for nexus_trader.
Tests cover DATA-01 through DATA-15 requirements.
Wave 0: All tests start as stubs (RED state — data modules not yet implemented).
Wave 1: Each test goes GREEN as corresponding data module is implemented.
"""

import pytest
import pandas as pd
import numpy as np
from data.universe import get_nse_universe
from data.market_data import MarketDataFetcher
from data.indicators import Indicators


class TestUniverse:
    """Tests for data/universe.py — DATA-01 (Nifty 100 universe)."""

    def test_universe_count(self):
        """DATA-01: NSE universe contains exactly 100 symbols."""
        u = get_nse_universe()
        assert len(u) == 100, f"Expected 100 symbols, got {len(u)}"

    def test_universe_format(self):
        """DATA-01: All symbols end in .NS and all dicts have 'sector' key."""
        u = get_nse_universe()
        assert all(s["symbol"].endswith(".NS") for s in u), "Some symbols don't end in .NS"
        assert all("sector" in s for s in u), "Some dicts missing 'sector' key"

    def test_universe_no_duplicates(self):
        """DATA-01: No duplicate symbols in the universe."""
        u = get_nse_universe()
        symbols = [s["symbol"] for s in u]
        assert len(set(symbols)) == 100, f"Duplicate symbols found: {len(u) - len(set(symbols))} duplicates"


class TestMarketDataFetcher:
    """Tests for data/market_data.py — DATA-01 through DATA-09."""

    def test_intraday_candles_bad_symbol(self, fetcher):
        """DATA-01: get_intraday_candles returns empty DataFrame on bad symbol without raising."""
        df = fetcher.get_intraday_candles("INVALID_XYZ_999.NS")
        assert df is not None, "Expected DataFrame, got None"
        assert df.empty, f"Expected empty DataFrame for bad symbol, got {len(df)} rows"

    def test_prepost_false(self, fetcher):
        """DATA-02: prepost=False is enforced on all yfinance calls (verified by code inspection)."""
        pytest.fail("not implemented yet")

    def test_rate_limit_delay(self, fetcher):
        """DATA-03: 0.2s sleep between sequential yfinance calls (verified by code inspection)."""
        pytest.fail("not implemented yet")

    def test_scalar_returns_none_on_failure(self, fetcher):
        """DATA-04: get_previous_close returns None on bad symbol without raising."""
        result = fetcher.get_previous_close("INVALID_XYZ_999.NS")
        assert result is None, f"Expected None for bad symbol, got {result}"

    def test_session_filter_09_15(self, fetcher):
        """DATA-05: get_intraday_candles rows all start at or after 09:15 IST (live network — manual verify)."""
        pytest.fail("not implemented yet")

    def test_global_indices_partial(self, fetcher, monkeypatch):
        """DATA-06: get_global_indices returns a dict (possibly partial) without raising."""
        import yfinance as yf

        original_ticker = yf.Ticker

        call_count = [0]

        def failing_ticker(symbol):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Simulated network failure for first symbol")
            return original_ticker(symbol)

        monkeypatch.setattr(yf, "Ticker", failing_ticker)
        result = fetcher.get_global_indices()
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_get_atr_fetcher(self, fetcher):
        """DATA-07: get_atr returns None on bad symbol without raising."""
        result = fetcher.get_atr("INVALID_XYZ_999.NS")
        assert result is None, f"Expected None for bad symbol ATR, got {result}"


class TestIndicators:
    """Tests for data/indicators.py — DATA-10 through DATA-15."""

    def test_vwap_no_nan(self, sample_ohlcv):
        """DATA-10: Indicators.vwap returns pd.Series with no NaN on valid OHLCV DataFrame."""
        result = Indicators.vwap(sample_ohlcv)
        assert isinstance(result, pd.Series), f"Expected pd.Series, got {type(result)}"
        assert not result.isna().any(), f"VWAP contains NaN values: {result.isna().sum()} NaN rows"

    def test_ema_output_shape(self, sample_ohlcv):
        """DATA-11: Indicators.ema returns pd.Series of same length as input DataFrame."""
        result = Indicators.ema(sample_ohlcv, period=9)
        assert isinstance(result, pd.Series), f"Expected pd.Series, got {type(result)}"
        assert len(result) == len(sample_ohlcv), f"EMA length {len(result)} != input length {len(sample_ohlcv)}"

    def test_rsi_bounds(self, sample_ohlcv):
        """DATA-12: Indicators.rsi dropna values are all in [0, 100]."""
        result = Indicators.rsi(sample_ohlcv)
        assert isinstance(result, pd.Series), f"Expected pd.Series, got {type(result)}"
        valid = result.dropna()
        assert (valid >= 0).all(), "RSI contains values below 0"
        assert (valid <= 100).all(), "RSI contains values above 100"

    def test_indicators_atr_returns_float(self, sample_ohlcv):
        """DATA-13: Indicators.atr returns a float (not NaN) on a valid OHLCV DataFrame."""
        result = Indicators.atr(sample_ohlcv)
        assert isinstance(result, float), f"Expected float, got {type(result)}"
        assert not pd.isna(result), "ATR returned NaN on valid DataFrame"

    def test_orb_tuple(self, sample_ohlcv):
        """DATA-14: Indicators.orb returns (high, low) tuple where high >= low."""
        high, low = Indicators.orb(sample_ohlcv, n_minutes=15)
        assert high >= low, f"ORB high {high} < low {low}"

    def test_volume_ratio_insufficient_data(self):
        """DATA-15: Indicators.volume_ratio returns 0.0 on 1-row DataFrame without raising."""
        df = pd.DataFrame(
            {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [102.0], "Volume": [50000.0]}
        )
        result = Indicators.volume_ratio(df)
        assert result == 0.0, f"Expected 0.0 for 1-row DataFrame, got {result}"
