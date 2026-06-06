"""
MarketDataFetcher — yfinance wrapper for nexus_trader.

All public methods return safe typed values on failure. No exceptions propagate to callers.
Error return contract:
  - Scalar methods (get_previous_close, get_premarket_price, get_atr) → None on failure
  - DataFrame methods (get_intraday_candles, get_historical_data) → pd.DataFrame() on failure
  - Dict methods (get_global_indices) → {} on failure

Rate limiting: 0.2s time.sleep() before every yfinance call (DATA-03 / D-01).
Session filtering: get_intraday_candles() returns rows from 09:15 IST onward only (D-05).
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
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "NIKKEI": "^N225",
    "HANGSENG": "^HSI",
    "CRUDE": "CL=F",
    "GOLD": "GC=F",
    "USDINR": "USDINR=X",
}


class MarketDataFetcher:
    """
    yfinance wrapper providing OHLCV data for NSE stocks and global indices.

    All methods are error-tolerant: they catch exceptions internally and return
    safe failure values (None / empty DataFrame / empty dict) instead of raising.
    """

    def _safe_fetch(self, symbol: str, **kwargs) -> pd.DataFrame:
        """
        Internal helper: sleep → fetch → guard.

        Sleeps 0.2s before every yfinance call to respect rate limits.
        Returns empty pd.DataFrame() on any failure (empty response, 429, exception).
        """
        time.sleep(_RATE_LIMIT_DELAY)
        try:
            df = yf.Ticker(symbol).history(**kwargs)
            if df is None or df.empty:
                logger.warning(
                    f"_safe_fetch({symbol}): empty response — possible 429 or delisted"
                )
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.error(f"_safe_fetch({symbol}): {e}")
            return pd.DataFrame()

    def get_previous_close(self, symbol: str) -> float | None:
        """
        Return the previous trading day's close price for a symbol.

        Returns None on failure (bad symbol, network error, insufficient data).
        """
        try:
            df = self._safe_fetch(
                symbol, period="5d", interval="1d", prepost=False, auto_adjust=True
            )
            if df.empty or len(df) < 2:
                logger.warning(
                    f"get_previous_close({symbol}): insufficient data (rows={len(df)})"
                )
                return None
            return float(df["Close"].iloc[-2])
        except Exception as e:
            logger.error(f"get_previous_close({symbol}): {e}")
            return None

    def get_premarket_price(self, symbol: str) -> float | None:
        """
        Return the most recent daily close as a premarket price proxy.

        Returns None on failure.
        """
        try:
            df = self._safe_fetch(
                symbol, period="2d", interval="1d", prepost=False, auto_adjust=True
            )
            if df.empty:
                logger.warning(f"get_premarket_price({symbol}): empty response")
                return None
            return float(df["Close"].iloc[-1])
        except Exception as e:
            logger.error(f"get_premarket_price({symbol}): {e}")
            return None

    def get_intraday_candles(self, symbol: str) -> pd.DataFrame:
        """
        Return today's intraday 5-min candles from 09:15 IST onward.

        Returns empty pd.DataFrame() on failure.
        Columns: Open, High, Low, Close, Volume
        """
        try:
            df = self._safe_fetch(
                symbol, period="1d", interval="5m", prepost=False, auto_adjust=True
            )
            if df.empty:
                return pd.DataFrame()

            # Convert UTC index to IST and filter to session start (09:15 IST)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert(IST)

            session_start = df.index[0].replace(hour=9, minute=15, second=0, microsecond=0)
            df = df[df.index >= session_start]

            if df.empty:
                return pd.DataFrame()

            return df[["Open", "High", "Low", "Close", "Volume"]].copy()
        except Exception as e:
            logger.error(f"get_intraday_candles({symbol}): {e}")
            return pd.DataFrame()

    def get_historical_data(self, symbol: str, period: str = "60d") -> pd.DataFrame:
        """
        Return daily OHLCV historical data for a symbol.

        Returns empty pd.DataFrame() on failure.
        Columns: Open, High, Low, Close, Volume
        """
        try:
            df = self._safe_fetch(
                symbol, period=period, interval="1d", prepost=False, auto_adjust=True
            )
            if df.empty:
                return pd.DataFrame()
            return df[["Open", "High", "Low", "Close", "Volume"]].copy()
        except Exception as e:
            logger.error(f"get_historical_data({symbol}): {e}")
            return pd.DataFrame()

    def get_atr(self, symbol: str, period: int = 14) -> float | None:
        """
        Fetch 30 days of daily data and compute ATR for a symbol.

        Used at watchlist build time (pre-market, no live DataFrame available).
        Returns None if data is insufficient or on any failure.
        Returns float on success.
        """
        try:
            df = self.get_historical_data(symbol, period="30d")
            if df.empty or len(df) < period + 1:
                logger.warning(
                    f"get_atr({symbol}): insufficient data (rows={len(df)}, need {period + 1})"
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
        except Exception as e:
            logger.error(f"get_atr({symbol}): {e}")
            return None

    def get_global_indices(self) -> dict[str, float]:
        """
        Fetch latest close for all 7 global indices.

        Returns a partial dict if some symbols fail — AgentI0 uses what's available.
        Returns empty {} only if all 7 fail.
        The outer method does not catch — only per-symbol try/except handles failures.
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
                    logger.warning(f"get_global_indices: {name} ({symbol}) returned empty")
            except Exception as e:
                logger.warning(f"get_global_indices: {name} ({symbol}) failed — {e}")
        return result


# Module-level startup log — fires once on import, warns all consumers of 15-min delay
logger.info("yfinance NSE data is 15 minutes delayed — embedded in all trade records.")
