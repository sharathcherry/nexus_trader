"""
MarketDataFetcher -- Hybrid fetcher for nexus_trader.
Uses Upstox API for NSE stocks (where mapped) and yfinance for global indices / fallbacks.

All public methods return safe typed values on failure. No exceptions propagate.
Error return contract:
  - Scalar methods  -> None on failure
  - DataFrame methods -> pd.DataFrame() on failure
  - Dict methods    -> {} on failure
"""

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import pytz
import requests
import yfinance as yf

from data.upstox_keys import UPSTOX_KEYS
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
    Hybrid fetcher: 
    - Upstox API for Indian equities (historical & intraday 1m resampled to 5m).
    - yfinance for global indices.
    All methods are error-tolerant: exceptions caught internally, safe values returned.
    """
    # Cache to share data across all fetcher instances
    _fetch_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
    _cache_ttl = 300  # 5 minutes TTL

    def __init__(self):
        self.upstox_token = None
        # Try reading from automated login token file first
        try:
            if os.path.exists(".upstox_token"):
                with open(".upstox_token", "r") as f:
                    self.upstox_token = f.read().strip()
        except Exception as e:
            logger.warning("Could not read .upstox_token: %s", e)
            
        if not self.upstox_token:
            self.upstox_token = os.getenv("UPSTOX_ACCESS_TOKEN")
            
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.upstox_token}'
        } if self.upstox_token else {}

    def _safe_fetch_yf(self, symbol: str, **kwargs) -> pd.DataFrame:
        """Internal helper for yfinance."""
        cache_key = ("YF", symbol, tuple(sorted(kwargs.items())))
        current_time = time.time()

        if cache_key in self._fetch_cache:
            cache_ts, cached_df = self._fetch_cache[cache_key]
            if current_time - cache_ts < self._cache_ttl:
                return cached_df.copy()

        time.sleep(_RATE_LIMIT_DELAY)
        try:
            df = yf.Ticker(symbol).history(**kwargs)
            if df is None or df.empty:
                logger.warning("_safe_fetch_yf(%s): empty response", symbol)
                return pd.DataFrame()
            self._fetch_cache[cache_key] = (current_time, df)
            return df.copy()
        except Exception as exc:
            logger.error("_safe_fetch_yf(%s): %s", symbol, exc)
            return pd.DataFrame()

    def _fetch_upstox_historical(self, instrument_key: str, interval: str, period_days: int) -> pd.DataFrame:
        """
        Fetch historical data from Upstox. Interval can be 'day', '1minute', etc.
        For intraday, we use the intraday endpoint. For day, we use the historical endpoint.
        """
        try:
            if not self.headers:
                logger.error("Upstox token not found in env.")
                return pd.DataFrame()

            if interval == "1minute":
                url = f"https://api.upstox.com/v2/historical-candle/intraday/{instrument_key}/1minute"
            else:
                to_date = datetime.now(IST).strftime('%Y-%m-%d')
                from_date = (datetime.now(IST) - timedelta(days=period_days)).strftime('%Y-%m-%d')
                url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"

            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code != 200:
                logger.warning("Upstox API error %d for %s: %s", resp.status_code, instrument_key, resp.text)
                return pd.DataFrame()
            
            data = resp.json().get('data', {}).get('candles', [])
            if not data:
                return pd.DataFrame()

            # Data format: [timestamp, open, high, low, close, vol, oi]
            # It is returned in reverse chronological order (newest first).
            df = pd.DataFrame(data, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'OI'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        except Exception as exc:
            logger.error("_fetch_upstox_historical(%s): %s", instrument_key, exc)
            return pd.DataFrame()

    def _safe_fetch(self, symbol: str, is_intraday=False, period_days=60) -> pd.DataFrame:
        """
        Hybrid router: routes to Upstox if symbol is mapped, else yfinance.
        For intraday, if using Upstox, fetches 1minute and resamples to 5minute.
        """
        cache_key = ("HYBRID", symbol, is_intraday, period_days)
        current_time = time.time()
        if cache_key in self._fetch_cache:
            cache_ts, cached_df = self._fetch_cache[cache_key]
            if current_time - cache_ts < self._cache_ttl:
                return cached_df.copy()

        instrument_key = UPSTOX_KEYS.get(symbol)
        df = pd.DataFrame()

        if instrument_key and self.headers:
            logger.debug("Fetching %s via Upstox API", symbol)
            if is_intraday:
                df = self._fetch_upstox_historical(instrument_key, "1minute", period_days=1)
                if not df.empty:
                    # Resample 1-minute to 5-minute
                    df = df.resample('5min').agg({
                        'Open': 'first',
                        'High': 'max',
                        'Low': 'min',
                        'Close': 'last',
                        'Volume': 'sum'
                    }).dropna()
            else:
                df = self._fetch_upstox_historical(instrument_key, "day", period_days=period_days)
        
        # Fallback to yfinance
        if df is None or df.empty:
            logger.debug("Fetching %s via yfinance fallback", symbol)
            if is_intraday:
                df = self._safe_fetch_yf(symbol, period="1d", interval="5m", prepost=False, auto_adjust=True)
                if not df.empty and df.index.tz is None:
                    df.index = df.index.tz_localize("UTC").tz_convert(IST)
                elif not df.empty:
                    df.index = df.index.tz_convert(IST)
            else:
                period_str = f"{period_days}d"
                df = self._safe_fetch_yf(symbol, period=period_str, interval="1d", prepost=False, auto_adjust=True)
                if not df.empty and df.index.tz is None:
                    df.index = df.index.tz_localize("UTC").tz_convert(IST)
                elif not df.empty:
                    df.index = df.index.tz_convert(IST)

        if df is not None and not df.empty:
            self._fetch_cache[cache_key] = (current_time, df)
            return df.copy()
            
        return pd.DataFrame()

    def get_previous_close(self, symbol: str) -> float | None:
        """Return the previous trading day's close price. None on failure."""
        try:
            df = self._safe_fetch(symbol, is_intraday=False, period_days=5)
            if df.empty or len(df) < 2:
                logger.warning("get_previous_close(%s): insufficient data", symbol)
                return None
            return float(df["Close"].iloc[-2])
        except Exception as exc:
            logger.error("get_previous_close(%s): %s", symbol, exc)
            return None

    def get_premarket_price(self, symbol: str) -> float | None:
        """
        Return today's opening price as the pre-market price proxy.
        """
        try:
            df_5m = self._safe_fetch(symbol, is_intraday=True)
            if not df_5m.empty:
                session_mask = (df_5m.index.hour > 9) | ((df_5m.index.hour == 9) & (df_5m.index.minute >= 15))
                session_df = df_5m[session_mask]
                if not session_df.empty:
                    return float(session_df["Open"].iloc[0])

            # Fallback: most recent daily close
            df_1d = self._safe_fetch(symbol, is_intraday=False, period_days=2)
            if not df_1d.empty:
                logger.debug("get_premarket_price(%s): intraday unavailable -- using daily close", symbol)
                return float(df_1d["Close"].iloc[-1])

            return None
        except Exception as exc:
            logger.error("get_premarket_price(%s): %s", symbol, exc)
            return None

    def get_intraday_candles(self, symbol: str) -> pd.DataFrame:
        """
        Return today's intraday 5-min candles from 09:15 IST onward.
        """
        try:
            df = self._safe_fetch(symbol, is_intraday=True)
            if df.empty:
                return pd.DataFrame()

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
            # Parse period (e.g., "60d" -> 60)
            period_days = int(period.replace("d", "")) if "d" in period else 60
            df = self._safe_fetch(symbol, is_intraday=False, period_days=period_days)
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
                return None

            high = df["High"]
            low = df["Low"]
            close = df["Close"]

            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ], axis=1).max(axis=1)

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
                df = self._safe_fetch_yf(symbol, period="2d", interval="1d", prepost=False, auto_adjust=True)
                if not df.empty:
                    result[name] = float(df["Close"].iloc[-1])
            except Exception as exc:
                logger.warning("get_global_indices: %s (%s) failed -- %s", name, symbol, exc)
        return result

# Module-level startup log
logger.info("MarketDataFetcher: Upstox API + yfinance fallback loaded.")
