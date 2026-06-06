---
wave: 1
plan_id: "02-PLAN-A"
phase: "02"
phase_name: "Data Layer"
objective: "Create data/universe.py (NSE 100 list) and data/market_data.py (MarketDataFetcher with all 8 methods)"
depends_on: []
files_modified:
  - data/universe.py
  - data/market_data.py
autonomous: true
requirements_addressed:
  - DATA-01
  - DATA-02
  - DATA-03
  - DATA-04
  - DATA-05
  - DATA-06
  - DATA-07
  - DATA-08
  - DATA-09
must_haves:
  truths:
    - "`get_nse_universe()` returns exactly 100 dicts, each with 'symbol' (ending .NS) and 'sector' keys"
    - "`MarketDataFetcher.get_previous_close('RELIANCE.NS')` returns a float without raising"
    - "`MarketDataFetcher.get_previous_close('INVALID.NS')` returns None without raising"
    - "`MarketDataFetcher.get_intraday_candles('RELIANCE.NS')` returns DataFrame with columns Open High Low Close Volume"
    - "Intraday DataFrame index contains only rows from 09:15 IST onward"
    - "`MarketDataFetcher.get_global_indices()` returns dict with up to 7 keys"
    - "`MarketDataFetcher.get_atr('RELIANCE.NS')` returns a float without raising"
    - "0.2s delay between sequential yfinance Ticker calls is enforced"
    - "No `ta` library imports anywhere in data/"
    - "Startup INFO log line: 'yfinance NSE data is 15 minutes delayed'"
---

# Phase 2 Plan A: NSE Universe + MarketDataFetcher

## Tasks

### Task 1: Create data/universe.py

<read_first>
- .planning/phases/02-data-layer/02-CONTEXT.md (D-03, D-04 — universe storage format)
- .planning/REQUIREMENTS.md (DATA-01)
</read_first>

<action>
Create `data/universe.py` with a single function `get_nse_universe() -> list[dict]`.

Returns a hardcoded list of exactly 100 dicts, each with keys:
- `"symbol"`: string ending in `.NS`
- `"sector"`: one of the standard sector strings

Use the 100 symbols from the research file (02-RESEARCH.md §"NSE universe"). Sectors:
Energy, Financial Services, IT, FMCG, Auto, Pharma, Metals, Telecom, Infra, Cement, Consumer Durables, Chemicals, Media, Realty.

Example structure:
```python
_NSE_UNIVERSE = [
    {"symbol": "RELIANCE.NS", "sector": "Energy"},
    {"symbol": "HDFCBANK.NS", "sector": "Financial Services"},
    ...
]

def get_nse_universe() -> list[dict]:
    return _NSE_UNIVERSE
```

No file I/O, no pandas, no external dependencies — pure Python list.
</action>

<acceptance_criteria>
- `data/universe.py` exists
- `python -c "from data.universe import get_nse_universe; u=get_nse_universe(); print(len(u))"` prints `100`
- `python -c "from data.universe import get_nse_universe; u=get_nse_universe(); assert all(s['symbol'].endswith('.NS') for s in u)"` exits 0
- `python -c "from data.universe import get_nse_universe; u=get_nse_universe(); assert all('sector' in s for s in u)"` exits 0
- All symbols are unique (no duplicates)
- `grep "import ta" data/universe.py` returns no match
</acceptance_criteria>

---

### Task 2: Create data/market_data.py — class skeleton + startup log

<read_first>
- .planning/phases/02-data-layer/02-CONTEXT.md (D-01, D-02, D-07 through D-10 — fetch pattern, error contract)
- .planning/phases/02-data-layer/02-RESEARCH.md §"yfinance Ticker.history() — correct call pattern"
- CLAUDE.md §"1. yfinance" (breaking changes, NSE timezone regression, rate limiting)
- config.py (import pattern reference)
- utils/logger.py (logger setup pattern)
</read_first>

<action>
Create `data/market_data.py` with class `MarketDataFetcher`.

Class structure:
```python
import time
import yfinance as yf
import pandas as pd
import pytz
from datetime import datetime
from utils.logger import setup_logger

logger = setup_logger(__name__)
logger.info("yfinance NSE data is 15 minutes delayed — embedded in all trade records")

IST = pytz.timezone("Asia/Kolkata")
_RATE_LIMIT_DELAY = 0.2  # seconds between yfinance calls

class MarketDataFetcher:
    def _safe_fetch(self, symbol: str, **kwargs) -> pd.DataFrame:
        """Internal: fetch with rate limit delay and empty-check."""
        time.sleep(_RATE_LIMIT_DELAY)
        try:
            df = yf.Ticker(symbol).history(**kwargs)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.warning(f"yfinance fetch failed for {symbol}: {e}")
            return pd.DataFrame()
```

The startup `logger.info(...)` about 15-min delay must be at module level (fires on import, not per-call).
</action>

<acceptance_criteria>
- `data/market_data.py` exists and imports without error
- `python -c "import data.market_data"` logs the 15-minute delay line to terminal
- `MarketDataFetcher` class exists
- `_safe_fetch` method exists and wraps all yfinance calls
- `grep "import ta" data/market_data.py` returns no match
</acceptance_criteria>

---

### Task 3: Implement get_previous_close() and get_premarket_price()

<read_first>
- .planning/phases/02-data-layer/02-RESEARCH.md §"yfinance Ticker.history() — correct call pattern"
- .planning/phases/02-data-layer/02-CONTEXT.md (D-07 — scalar methods return None on failure)
- .planning/REQUIREMENTS.md (DATA-02, DATA-03)
</read_first>

<action>
Add to `MarketDataFetcher`:

```python
def get_previous_close(self, symbol: str) -> float | None:
    df = self._safe_fetch(symbol, period="5d", interval="1d", prepost=False)
    if df.empty or len(df) < 2:
        return None
    return float(df["Close"].iloc[-2])

def get_premarket_price(self, symbol: str) -> float | None:
    """Returns latest available price (last close — yfinance has no true pre-market for NSE)."""
    df = self._safe_fetch(symbol, period="2d", interval="1d", prepost=False)
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])
```

Both return `None` on any failure — no exceptions propagate to callers.
</action>

<acceptance_criteria>
- `get_previous_close('RELIANCE.NS')` returns a positive float on a market day
- `get_previous_close('INVALID_XYZ_999.NS')` returns `None` without raising
- `get_premarket_price('RELIANCE.NS')` returns a positive float
- `get_premarket_price('INVALID_XYZ_999.NS')` returns `None` without raising
- Both methods use `self._safe_fetch()` internally (no direct `yf.Ticker` calls)
</acceptance_criteria>

---

### Task 4: Implement get_intraday_candles() with session filtering

<read_first>
- .planning/phases/02-data-layer/02-RESEARCH.md §"NSE timezone handling" and §"yfinance Ticker.history() — correct call pattern"
- .planning/phases/02-data-layer/02-CONTEXT.md (D-05 — caller filters, D-08 — tabular returns empty DataFrame)
- .planning/REQUIREMENTS.md (DATA-04)
</read_first>

<action>
Add to `MarketDataFetcher`:

```python
def get_intraday_candles(self, symbol: str) -> pd.DataFrame:
    df = self._safe_fetch(symbol, period="1d", interval="5m", prepost=False)
    if df.empty:
        return pd.DataFrame()
    # Convert UTC index to IST, filter to 09:15+ only
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(IST)
    session_start = df.index[0].replace(hour=9, minute=15, second=0, microsecond=0)
    df = df[df.index >= session_start]
    return df[["Open", "High", "Low", "Close", "Volume"]].copy()
```

Returns only standard OHLCV columns. Empty DataFrame on any failure or empty result.
</action>

<acceptance_criteria>
- `get_intraday_candles('RELIANCE.NS')` returns DataFrame with columns `['Open', 'High', 'Low', 'Close', 'Volume']`
- All rows in returned DataFrame have index time >= 09:15 IST
- `get_intraday_candles('INVALID_XYZ_999.NS')` returns empty DataFrame without raising
- `df.empty` check on bad symbol returns `True`
</acceptance_criteria>

---

### Task 5: Implement get_historical_data() and get_atr()

<read_first>
- .planning/phases/02-data-layer/02-RESEARCH.md §"get_atr() in MarketDataFetcher vs Indicators.atr()"
- .planning/phases/02-data-layer/02-CONTEXT.md (D-11 — ATR split, D-07/D-08 error contract)
- .planning/REQUIREMENTS.md (DATA-05, DATA-07)
</read_first>

<action>
Add to `MarketDataFetcher`:

```python
def get_historical_data(self, symbol: str, period: str = "60d") -> pd.DataFrame:
    df = self._safe_fetch(symbol, period=period, interval="1d", prepost=False)
    if df.empty:
        return pd.DataFrame()
    return df[["Open", "High", "Low", "Close", "Volume"]].copy()

def get_atr(self, symbol: str, period: int = 14) -> float | None:
    df = self.get_historical_data(symbol, period="30d")
    if df.empty or len(df) < period + 1:
        return None
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr_val = tr.rolling(period).mean().iloc[-1]
    return float(atr_val) if not pd.isna(atr_val) else None
```
</action>

<acceptance_criteria>
- `get_historical_data('RELIANCE.NS')` returns DataFrame with OHLCV columns and > 30 rows
- `get_historical_data('INVALID_XYZ_999.NS')` returns empty DataFrame
- `get_atr('RELIANCE.NS')` returns a positive float
- `get_atr('INVALID_XYZ_999.NS')` returns `None` without raising
- `get_atr` does NOT import or call any `ta` library function
</acceptance_criteria>

---

### Task 6: Implement get_global_indices()

<read_first>
- .planning/phases/02-data-layer/02-RESEARCH.md §"Global indices — correct yfinance symbols"
- .planning/phases/02-data-layer/02-CONTEXT.md (D-09 — dict methods return {} on failure)
- .planning/REQUIREMENTS.md (DATA-06)
</read_first>

<action>
Add to `MarketDataFetcher`:

```python
_GLOBAL_INDICES = {
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "NIKKEI": "^N225",
    "HANGSENG": "^HSI",
    "CRUDE": "CL=F",
    "GOLD": "GC=F",
    "USDINR": "USDINR=X",
}

def get_global_indices(self) -> dict[str, float]:
    result = {}
    for name, symbol in _GLOBAL_INDICES.items():
        try:
            df = self._safe_fetch(symbol, period="2d", interval="1d", prepost=False)
            if not df.empty:
                result[name] = float(df["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"Global index {name} ({symbol}) fetch failed: {e}")
            # partial result — continue without this index
    return result
```

Partial results are acceptable — AgentI0 uses what's available. Returns `{}` only if all 7 fail.
</action>

<acceptance_criteria>
- `get_global_indices()` returns a dict (possibly partial) on a market day
- `get_global_indices()` never raises — returns `{}` or partial dict on total failure
- All values in returned dict are positive floats
- `_GLOBAL_INDICES` constant has exactly 7 entries
- `grep "import ta" data/market_data.py` returns no match
</acceptance_criteria>

