"""
MarketDataFetcher -- yfinance wrapper for nexus_trader.

All public methods return safe typed values on failure. No exceptions propagate.
Error return contract:
  - Scalar methods  -> None on failure
  - DataFrame methods -> pd.DataFrame() on failure
  - Dict methods    -> {} on failure

Rate limiting: 0.2s time.sleep() before every yfinance call.
Session filtering: get_intraday_candles() returns rows from 09:15 IST onward.
"""

import time

import pandas as pd
import pytz
import yfinance as yf

from utils.logger import setup_logger

logger = setup_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")
_RATE_LIMIT_DELAY = 0.2

_GLOBAL_INDICES = {
    "SP500":    "^GSPC",
    "NASDAQ":   "^IXIC",
    "NIKKEI":   "^N225",
    "HANGSENG": "^HSI",
    "CRUDE":    "CL=F",
    "GOLD":     "GC=F",
    "USDINR":   "USDINR=X",
}


class MarketDataFetcher:
    """
    yfinance wrapper providing OHLCV data for NSE stocks and global indices.
    All methods are error-tolerant: exceptions caught internally, safe values returned.
    """
    # Class-level cache to share cached data across all fetcher instances
    _fetch_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
    _cache_ttl = 300  # 5 minutes TTL

    def _safe_fetch(self, symbol: str, **kwargs) -> pd.DataFrame:
        """
        Internal helper: sleep -> fetch -> guard.
        Sleeps 0.2s before every yfinance call (rate-limit guard) unless cached.
        Returns empty pd.DataFrame() on any failure.
        """
        current_time = time.time()
        # Build cache key from symbol and kwargs
        cache_key = (symbol, tuple(sorted(kwargs.items())))

        if cache_key in self._fetch_cache:
            cache_ts, cached_df = self._fetch_cache[cache_key]
            if current_time - cache_ts < self._cache_ttl:
                logger.debug("MarketDataFetcher: returning cached data for %s", symbol)
                return cached_df.copy()

        # Cache miss: sleep and fetch
        time.sleep(_RATE_LIMIT_DELAY)
        try:
            df = yf.Ticker(symbol).history(**kwargs)
            if df is None or df.empty:
                logger.warning(
                    "_safe_fetch(%s): empty response -- possible 429 or delisted", symbol
                )
                return pd.DataFrame()
            self._fetch_cache[cache_key] = (current_time, df)
            return df.copy()
        except Exception as exc:
            logger.error("_safe_fetch(%s): %s", symbol, exc)
            return pd.DataFrame()

    def get_previous_close(self, symbol: str) -> float | None:
        """Return the previous trading day's close price. None on failure."""
        try:
            df = self._safe_fetch(
                symbol, period="5d", interval="1d", prepost=False, auto_adjust=True
            )
            if df.empty or len(df) < 2:
                logger.warning(
                    "get_previous_close(%s): insufficient data (rows=%d)", symbol, len(df)
                )
                return None
            return float(df["Close"].iloc[-2])
        except Exception as exc:
            logger.error("get_previous_close(%s): %s", symbol, exc)
            return None

    def get_premarket_price(self, symbol: str) -> float | None:
        """
        Return today's opening price as the pre-market price proxy.

        NSE has no true pre-market session accessible via yfinance. The best
        free proxy is today's opening candle (09:15 IST), which reflects the
        gap-open relative to yesterday's close.

        Strategy:
          1. Fetch today's 5-min intraday data.
          2. Return the Open price of the first session candle (09:15 bar).
          3. If intraday data is unavailable (called pre-09:15 or holiday),
             fall back to the most recent daily close.
        """
        try:
            df_5m = self._safe_fetch(
                symbol, period="1d", interval="5m", prepost=False, auto_adjust=True
            )
            if not df_5m.empty:
                if df_5m.index.tz is None:
                    df_5m.index = df_5m.index.tz_localize("UTC")
                df_5m.index = df_5m.index.tz_convert(IST)
                session_mask = (df_5m.index.hour > 9) | (
                    (df_5m.index.hour == 9) & (df_5m.index.minute >= 15)
                )
                session_df = df_5m[session_mask]
                if not session_df.empty:
                    return float(session_df["Open"].iloc[0])

            # Fallback: most recent daily close
            df_1d = self._safe_fetch(
                symbol, period="2d", interval="1d", prepost=False, auto_adjust=True
            )
            if not df_1d.empty:
                logger.debug(
                    "get_premarket_price(%s): intraday unavailable -- using daily close fallback",
                    symbol,
                )
                return float(df_1d["Close"].iloc[-1])

            logger.warning("get_premarket_price(%s): all sources empty", symbol)
            return None
        except Exception as exc:
            logger.error("get_premarket_price(%s): %s", symbol, exc)
            return None

    def get_intraday_candles(self, symbol: str) -> pd.DataFrame:
        """
        Return today's intraday 5-min candles from 09:15 IST onward.
        Returns empty pd.DataFrame() on failure.
        """
        try:
            df = self._safe_fetch(
                symbol, period="1d", interval="5m", prepost=False, auto_adjust=True
            )
            if df.empty:
                return pd.DataFrame()

            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert(IST)

            session_start = df.index[0].replace(hour=9, minute=15, second=0, microsecond=0)
            df = df[df.index >= session_start]

            if df.empty:
                return pd.DataFrame()

            return df[["Open", "High", "Low", "Close", "Volume"]].copy()
        except Exception as exc:
            logger.error("get_intraday_candles(%s): %s", symbol, exc)
            return pd.DataFrame()

    def get_historical_data(self, symbol: str, period: str = "60d") -> pd.DataFrame:
        """Return daily OHLCV historical data. Returns empty DataFrame on failure."""
        try:
            df = self._safe_fetch(
                symbol, period=period, interval="1d", prepost=False, auto_adjust=True
            )
            if df.empty:
                return pd.DataFrame()
            return df[["Open", "High", "Low", "Close", "Volume"]].copy()
        except Exception as exc:
            logger.error("get_historical_data(%s): %s", symbol, exc)
            return pd.DataFrame()

    def get_atr(self, symbol: str, period: int = 14) -> float | None:
        """
        Fetch 30 days of daily data and compute ATR.
        Returns None if data is insufficient or on any failure.
        """
        try:
            df = self.get_historical_data(symbol, period="30d")
            if df.empty or len(df) < period + 1:
                logger.warning(
                    "get_atr(%s): insufficient data (rows=%d, need %d)",
                    symbol, len(df), period + 1,
                )
                return None

            high = df["High"]
            low = df["Low"]
            close = df["Close"]

            tr = pd.concat(
                [
                    high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs(),
                ],
                axis=1,
            ).max(axis=1)

            atr_val = tr.rolling(period).mean().iloc[-1]
            return float(atr_val) if not pd.isna(atr_val) else None
        except Exception as exc:
            logger.error("get_atr(%s): %s", symbol, exc)
            return None

    def get_global_indices(self) -> dict[str, float]:
        """
        Fetch latest close for all global indices.
        Returns partial dict if some fail. Returns {} only if all fail.
        """
        result: dict[str, float] = {}
        for name, symbol in _GLOBAL_INDICES.items():
            try:
                df = self._safe_fetch(
                    symbol, period="2d", interval="1d", prepost=False, auto_adjust=True
                )
                if not df.empty:
                    result[name] = float(df["Close"].iloc[-1])
                else:
                    logger.warning(
                        "get_global_indices: %s (%s) returned empty", name, symbol
                    )
            except Exception as exc:
                logger.warning(
                    "get_global_indices: %s (%s) failed -- %s", name, symbol, exc
                )
        return result


# Module-level startup log
logger.info("yfinance NSE data is 15 minutes delayed -- embedded in all trade records.")
