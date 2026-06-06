---
wave: 1
plan_id: "02-PLAN-B"
phase: "02"
phase_name: "Data Layer"
objective: "Create data/indicators.py (Indicators class with VWAP, EMA, RSI, ATR, ORB, volume_ratio)"
depends_on: []
files_modified:
  - data/indicators.py
autonomous: true
requirements_addressed:
  - DATA-10
  - DATA-11
  - DATA-12
  - DATA-13
  - DATA-14
  - DATA-15
must_haves:
  truths:
    - "`Indicators.vwap(df)` returns pd.Series with no NaN when df is a valid session DataFrame"
    - "`Indicators.ema(df, period=20)` returns pd.Series"
    - "`Indicators.rsi(df, period=14)` returns pd.Series with values between 0 and 100"
    - "`Indicators.atr(df, period=14)` returns a float (not NaN)"
    - "`Indicators.orb(df, n_minutes=15)` returns tuple (orb_high, orb_low) where orb_high > orb_low"
    - "`Indicators.volume_ratio(df)` returns a non-negative float"
    - "No `ta` library imports anywhere in data/indicators.py"
    - "All methods are @staticmethod"
---

# Phase 2 Plan B: Indicators Class

## Tasks

### Task 1: Create data/indicators.py skeleton

<read_first>
- .planning/phases/02-data-layer/02-CONTEXT.md (D-05, D-06 — indicator input contract, ORB config)
- .planning/phases/02-data-layer/02-RESEARCH.md §"Inline pandas indicators — implementation patterns"
- .planning/REQUIREMENTS.md (DATA-10 through DATA-15)
- config.py (for ORB_MINUTES default reference)
</read_first>

<action>
Create `data/indicators.py`:

```python
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
```

No instance state. All 6 methods are `@staticmethod`. File imports only `pandas`, `numpy`, `utils.logger` — no `ta`, no `yfinance`.
</action>

<acceptance_criteria>
- `data/indicators.py` exists and imports without error
- `from data.indicators import Indicators` exits 0
- `grep "import ta" data/indicators.py` returns no match
- `grep "import yfinance" data/indicators.py` returns no match
</acceptance_criteria>

---

### Task 2: Implement vwap() and ema()

<read_first>
- .planning/phases/02-data-layer/02-RESEARCH.md §"Inline pandas indicators — VWAP" and §"EMA"
- .planning/REQUIREMENTS.md (DATA-10, DATA-11)
</read_first>

<action>
Add to `Indicators`:

```python
@staticmethod
def vwap(df: pd.DataFrame) -> pd.Series:
    """Session-reset VWAP. Caller ensures df starts at 09:15 IST."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_tp_vol = (typical * df["Volume"]).cumsum()
    cum_vol = df["Volume"].cumsum()
    return cum_tp_vol / cum_vol

@staticmethod
def ema(df: pd.DataFrame, period: int = 20, column: str = "Close") -> pd.Series:
    return df[column].ewm(span=period, adjust=False).mean()
```
</action>

<acceptance_criteria>
- `Indicators.vwap(df)` returns `pd.Series` of same length as `df`
- VWAP series has no NaN when `df` has valid OHLCV with non-zero volume
- `Indicators.ema(df, period=9)` returns `pd.Series` of same length as `df`
- EMA values are positive for typical price data
- Both methods accept a DataFrame with columns `Open High Low Close Volume`
</acceptance_criteria>

---

### Task 3: Implement rsi() and atr()

<read_first>
- .planning/phases/02-data-layer/02-RESEARCH.md §"Inline pandas indicators — RSI" and §"ATR"
- .planning/phases/02-data-layer/02-CONTEXT.md (D-11 — Indicators.atr() vs MarketDataFetcher.get_atr())
- .planning/REQUIREMENTS.md (DATA-12, DATA-13)
</read_first>

<action>
Add to `Indicators`:

```python
@staticmethod
def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))

@staticmethod
def atr(df: pd.DataFrame, period: int = 14) -> float:
    """Returns latest ATR value from supplied DataFrame."""
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if not pd.isna(val) else 0.0
```

Note: `Indicators.atr()` receives a caller-supplied DataFrame (intraday or daily). `MarketDataFetcher.get_atr()` fetches daily data internally and calls this or equivalent logic — they are separate methods serving different call sites.
</action>

<acceptance_criteria>
- `Indicators.rsi(df)` returns `pd.Series` with values between 0 and 100 (ignoring initial NaN rows)
- `Indicators.rsi(df).iloc[-1]` is a float between 0 and 100 on a >20-row DataFrame
- `Indicators.atr(df)` returns a positive float on a valid OHLCV DataFrame with > 14 rows
- `Indicators.atr(df)` returns `0.0` (not NaN, not raises) when DataFrame is too short
- Neither method imports `ta`
</acceptance_criteria>

---

### Task 4: Implement orb() and volume_ratio()

<read_first>
- .planning/phases/02-data-layer/02-RESEARCH.md §"Inline pandas indicators — ORB" and §"volume_ratio"
- .planning/phases/02-data-layer/02-CONTEXT.md (D-06 — ORB uses config.ORB_MINUTES default)
- .planning/REQUIREMENTS.md (DATA-14, DATA-15)
</read_first>

<action>
Add to `Indicators`:

```python
@staticmethod
def orb(df: pd.DataFrame, n_minutes: int = 15) -> tuple[float, float]:
    """Opening range high/low for first n_minutes of session.
    Caller ensures df starts at 09:15 IST (each row = 1 candle = 5 min for 5m data).
    n_minutes=15 with 5m candles = first 3 rows."""
    n_candles = max(1, n_minutes // 5)  # assumes 5-min candles
    opening = df.head(n_candles)
    if opening.empty:
        return (0.0, 0.0)
    return (float(opening["High"].max()), float(opening["Low"].min()))

@staticmethod
def volume_ratio(df: pd.DataFrame, lookback: int = 20) -> float:
    """Current candle volume / average of previous `lookback` candles."""
    if len(df) < 2:
        return 0.0
    current_vol = df["Volume"].iloc[-1]
    avg_vol = df["Volume"].iloc[:-1].tail(lookback).mean()
    if avg_vol == 0 or pd.isna(avg_vol):
        return 0.0
    return float(current_vol / avg_vol)
```
</action>

<acceptance_criteria>
- `Indicators.orb(df)` returns tuple `(high, low)` where `high >= low`
- `Indicators.orb(df, n_minutes=15)` on a 5-min DataFrame uses first 3 candles
- `Indicators.orb(df)` returns `(0.0, 0.0)` when DataFrame is empty (no raise)
- `Indicators.volume_ratio(df)` returns a positive float on a valid DataFrame with > 2 rows
- `Indicators.volume_ratio(df)` returns `0.0` on a 1-row DataFrame (no raise)
- `grep "import ta" data/indicators.py` returns no match
</acceptance_criteria>

---

## Verification

```bash
# No ta imports
grep -r "import ta" data/

# Universe check
python -c "
from data.universe import get_nse_universe
u = get_nse_universe()
assert len(u) == 100, f'Got {len(u)} symbols'
assert all(s['symbol'].endswith('.NS') for s in u)
assert all('sector' in s for s in u)
symbols = [s['symbol'] for s in u]
assert len(set(symbols)) == 100, 'Duplicate symbols found'
print('Universe OK: 100 unique .NS symbols')
"

# Indicators unit test (offline — no network)
python -c "
import pandas as pd
import numpy as np
from data.indicators import Indicators

# Build a synthetic 30-row 5-min OHLCV DataFrame
n = 30
df = pd.DataFrame({
    'Open':   np.linspace(500, 520, n),
    'High':   np.linspace(505, 525, n),
    'Low':    np.linspace(495, 515, n),
    'Close':  np.linspace(502, 522, n),
    'Volume': np.random.randint(10000, 50000, n).astype(float),
})

vwap = Indicators.vwap(df)
assert len(vwap) == n and not vwap.isna().any(), 'VWAP failed'

ema = Indicators.ema(df, period=9)
assert len(ema) == n, 'EMA failed'

rsi = Indicators.rsi(df)
valid_rsi = rsi.dropna()
assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all(), 'RSI out of range'

atr_val = Indicators.atr(df, period=14)
assert isinstance(atr_val, float) and atr_val > 0, f'ATR failed: {atr_val}'

orb_h, orb_l = Indicators.orb(df, n_minutes=15)
assert orb_h >= orb_l, 'ORB high < low'

vr = Indicators.volume_ratio(df)
assert isinstance(vr, float) and vr >= 0, f'VolumeRatio failed: {vr}'

print('All indicator tests passed')
"
```
