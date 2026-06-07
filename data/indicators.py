"""
Indicators — stateless technical analysis calculations for nexus_trader.

All methods are @staticmethod — no instance state, no network calls.
Callers MUST pass a session-filtered DataFrame (09:15 IST onward).
VWAP reset is implicit — the DataFrame starts at 09:15.

No ta library — all computations are inline pandas/numpy.
"""

import pandas as pd
import numpy as np

from utils.logger import setup_logger

logger = setup_logger(__name__)


class Indicators:
    """
    Stateless indicator calculations. All methods are @staticmethod.
    Callers MUST pass a session-filtered DataFrame (09:15 IST onward).
    VWAP reset is implicit — the DataFrame starts at 09:15.
    """

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        """
        Session-reset VWAP. Caller ensures df starts at 09:15 IST.

        Returns pd.Series of same length as df.
        """
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_tp_vol = (typical * df["Volume"]).cumsum()
        cum_vol = df["Volume"].cumsum().replace(0, np.nan)
        return (cum_tp_vol / cum_vol).fillna(df["Close"])

    @staticmethod
    def ema(df: pd.DataFrame, period: int = 20, column: str = "Close") -> pd.Series:
        """
        Exponential Moving Average using ewm (standard EMA, adjust=False).

        Returns pd.Series of same length as df.
        """
        return df[column].ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Relative Strength Index.

        Returns pd.Series of same length as df.
        Initial rows will have NaN (normal for rolling window).
        Callers use .dropna() before bounding checks.
        """
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        # Prevent division by zero when loss is 0 (all gains, RSI = 100)
        rs = gain / loss.replace(0, float("nan"))
        rsi = 100 - (100 / (1 + rs))
        # Handle edge cases where loss is 0 or price is flat
        rsi.loc[(gain > 0) & (loss == 0)] = 100.0
        rsi.loc[(gain == 0) & (loss == 0)] = 50.0
        return rsi

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> float:
        """
        Average True Range from a caller-supplied DataFrame.

        Returns latest ATR value as float.
        Returns 0.0 (not NaN, not raises) when DataFrame is too short to compute ATR.

        Note: MarketDataFetcher.get_atr() is a separate implementation that fetches
        daily data internally. This method receives an already-fetched DataFrame.
        """
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

        val = tr.rolling(period).mean().iloc[-1]
        return float(val) if not pd.isna(val) else 0.0

    @staticmethod
    def orb(df: pd.DataFrame, n_minutes: int = None) -> tuple[float, float]:
        """
        Opening Range High/Low for first n_minutes of the session.

        Assumes 5-min candles. Default resolves from config.ORB_MINUTES (15) → first 3 rows.
        Returns (orb_high, orb_low) tuple where orb_high >= orb_low.
        Returns (0.0, 0.0) on empty DataFrame.

        n_minutes=None sentinel triggers late import of config.ORB_MINUTES (avoids
        circular import at module level).
        """
        if n_minutes is None:
            from config import config  # late import to avoid circular at module level
            n_minutes = config.ORB_MINUTES

        n_candles = max(1, n_minutes // 5)
        opening = df.head(n_candles)

        if opening.empty:
            return (0.0, 0.0)

        return (float(opening["High"].max()), float(opening["Low"].min()))

    @staticmethod
    def volume_ratio(df: pd.DataFrame, lookback: int = 20) -> float:
        """
        Current bar volume relative to average of preceding bars.

        Returns 0.0 when DataFrame has fewer than 2 rows (insufficient for comparison).
        Returns 0.0 when average volume is zero or NaN.
        Returns float ratio otherwise.
        """
        if len(df) < 2:
            return 0.0

        current_vol = df["Volume"].iloc[-1]
        avg_vol = df["Volume"].iloc[:-1].tail(lookback).mean()

        if avg_vol == 0 or pd.isna(avg_vol):
            return 0.0

        return float(current_vol / avg_vol)
