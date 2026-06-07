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
        """DATA-02: prepost=False is enforced — verify by patching _safe_fetch and inspecting kwargs."""
        import yfinance as yf
        from unittest.mock import patch, MagicMock

        captured_kwargs = []

        original_safe_fetch = fetcher._safe_fetch

        def capturing_safe_fetch(symbol, **kwargs):
            captured_kwargs.append(kwargs)
            # Return empty DF so no network call
            return pd.DataFrame()

        with patch.object(fetcher, "_safe_fetch", side_effect=capturing_safe_fetch):
            fetcher.get_intraday_candles("RELIANCE.NS")
            fetcher.get_previous_close("RELIANCE.NS")
            fetcher.get_historical_data("RELIANCE.NS", period="5d")

        for kwargs in captured_kwargs:
            assert kwargs.get("prepost") is False, (
                f"prepost=False not enforced — got prepost={kwargs.get('prepost')!r} "
                f"in call with kwargs={kwargs}"
            )

    def test_rate_limit_delay(self, fetcher):
        """DATA-03: _safe_fetch calls time.sleep(0.2) before every yfinance call."""
        import data.market_data as mdata
        from unittest.mock import patch, MagicMock, call

        sleep_calls = []

        def track_sleep(seconds):
            sleep_calls.append(seconds)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with patch.object(mdata.time, "sleep", side_effect=track_sleep):
            with patch("data.market_data.yf.Ticker", return_value=mock_ticker):
                fetcher.get_intraday_candles("RELIANCE.NS")
                fetcher.get_previous_close("TCS.NS")

        assert len(sleep_calls) >= 2, f"Expected at least 2 sleep calls, got {sleep_calls}"
        for s in sleep_calls:
            assert s == 0.2, f"Expected sleep(0.2), got sleep({s})"

    def test_scalar_returns_none_on_failure(self, fetcher):
        """DATA-04: get_previous_close returns None on bad symbol without raising."""
        result = fetcher.get_previous_close("INVALID_XYZ_999.NS")
        assert result is None, f"Expected None for bad symbol, got {result}"

    def test_session_filter_09_15(self, fetcher):
        """DATA-05: get_intraday_candles filters rows to >= 09:15 IST."""
        import data.market_data as mdata
        import pytz
        import pandas as pd
        from unittest.mock import patch, MagicMock

        IST = pytz.timezone("Asia/Kolkata")

        # Build a fake 5-min DataFrame with rows from 08:45 IST to 10:00 IST
        # (simulating pre-session + session candles as yfinance would return them)
        times_ist = pd.date_range(
            start="2026-06-06 08:45:00",
            end="2026-06-06 10:00:00",
            freq="5min",
            tz=IST,
        )
        # Convert to UTC as yfinance returns UTC timestamps
        times_utc = times_ist.tz_convert("UTC")
        fake_df = pd.DataFrame(
            {
                "Open":   [100.0] * len(times_utc),
                "High":   [101.0] * len(times_utc),
                "Low":    [99.0]  * len(times_utc),
                "Close":  [100.5] * len(times_utc),
                "Volume": [100_000] * len(times_utc),
            },
            index=times_utc,
        )

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_df

        with patch("data.market_data.yf.Ticker", return_value=mock_ticker):
            result = fetcher.get_intraday_candles("RELIANCE.NS")

        assert not result.empty, "Expected non-empty DataFrame after filter"

        # All rows must be at or after 09:15 IST
        session_start_time = result.index[0].astimezone(IST)
        assert session_start_time.hour > 9 or (
            session_start_time.hour == 9 and session_start_time.minute >= 15
        ), (
            f"First row is before 09:15 IST: {session_start_time.strftime('%H:%M')}"
        )

        # The 08:45, 08:50 ... 09:10 rows should be filtered out
        # The earliest remaining row should be 09:15
        for ts in result.index:
            ts_ist = ts.astimezone(IST)
            assert ts_ist.hour > 9 or (ts_ist.hour == 9 and ts_ist.minute >= 15), (
                f"Row at {ts_ist.strftime('%H:%M')} IST should have been filtered out"
            )

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
