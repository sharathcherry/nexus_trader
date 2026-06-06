# Phase 2: Data Layer - Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 5 (3 new modules + 2 new test files)
**Analogs found:** 3 / 5 (2 test files have no analog — no tests exist yet)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `data/universe.py` | utility | static-lookup | `config.py` | role-match (hardcoded data store) |
| `data/market_data.py` | service | request-response | `main.py` + `config.py` | partial (import + logger pattern) |
| `data/indicators.py` | utility | transform | `main.py` | partial (import + logger pattern) |
| `tests/test_data_layer.py` | test | batch | none | no analog |
| `tests/conftest.py` | config | static-lookup | none | no analog |

---

## Pattern Assignments

### `data/universe.py` (utility, static-lookup)

**Analog:** `config.py`

The closest structural analog is `config.py`: a module that holds hardcoded configuration data in a Python class/object and exposes it via a single well-known import. `universe.py` follows the same idea — hardcoded data, no I/O, version-controlled, one public function.

**Imports pattern** (`config.py` lines 1-4):
```python
import os
from dotenv import load_dotenv
```
For `universe.py`, no external imports are needed — pure Python list of dicts. Module-level docstring describing the static nature of the data is the primary convention to copy.

**Module-level data + single accessor pattern** (`config.py` lines 7-57 — adapted):
```python
# config.py establishes: define data at module level, expose via a named object/function
config = Config()   # line 57 — single public name exported from module
```

Apply the same pattern to universe.py:
```python
# data/universe.py — copy this structural idiom from config.py
_NSE_UNIVERSE = [
    {"symbol": "RELIANCE.NS", "sector": "Energy"},
    # ... 99 more
]

def get_nse_universe() -> list[dict]:
    """Return the Nifty 100 universe as a list of dicts with 'symbol' and 'sector' keys."""
    return _NSE_UNIVERSE
```

**No logger** — pure data module, no logger needed. `config.py` itself has no logger.

---

### `data/market_data.py` (service, request-response)

**Analog:** `main.py` (import + logger pattern) + `config.py` (config access pattern)

This is the most complex new file. No existing service analog exists. Use the import/logger conventions from `main.py` and the config access from `config.py`.

**Imports pattern** (`main.py` lines 1-4):
```python
from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)
```
These three lines appear at the top of every module-with-logic. Copy verbatim into `market_data.py`.

**Config access pattern** (`config.py` line 57 + `main.py` line 1):
```python
# config.py exposes the singleton:
config = Config()

# main.py (and every future module) imports it as:
from config import config
# Then uses: config.CAPITAL, config.ORB_MINUTES, etc.
```

**Class structure pattern** (`config.py` lines 7-57 — class with `__init__` and methods):
```python
class Config:
    def __init__(self):
        self.CAPITAL = 100_000
        # ...

    def _require(self, key: str) -> str:
        # private helper
```
`MarketDataFetcher` should follow the same class-with-`__init__` pattern. `__init__` sets up any instance state (e.g., storing IST timezone constant). Private helpers prefixed with `_`.

**Error return contract** (from CONTEXT.md D-07/D-08/D-09 — no codebase analog, use research):
```python
# Scalar methods return None on failure
def get_previous_close(self, symbol: str) -> float | None:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d", interval="1d", prepost=False, auto_adjust=True)
        if df is None or df.empty:
            logger.warning(f"get_previous_close({symbol}): empty response")
            return None
        return float(df["Close"].iloc[-2])
    except Exception as e:
        logger.error(f"get_previous_close({symbol}): {e}")
        return None

# DataFrame methods return empty pd.DataFrame() on failure
def get_intraday_candles(self, symbol: str) -> pd.DataFrame:
    try:
        # ... fetch logic ...
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        logger.error(f"get_intraday_candles({symbol}): {e}")
        return pd.DataFrame()

# Dict methods return empty {} on failure
def get_global_indices(self) -> dict[str, float]:
    try:
        # ... fetch loop ...
    except Exception as e:
        logger.error(f"get_global_indices: {e}")
        return {}
```

**Logger warning pattern for 429/empty** (`utils/logger.py` lines 9-54 — level conventions):
- `logger.DEBUG` — normal fetch attempts
- `logger.WARNING` — empty DataFrame returned (possible 429 or delisted symbol)
- `logger.ERROR` — exception caught inside try/except

---

### `data/indicators.py` (utility, transform)

**Analog:** `main.py` (import + logger pattern)

Pure computation module. All methods are `@staticmethod` (per CONTEXT.md). Logger is used only for warnings when inputs are malformed.

**Imports pattern** (`main.py` lines 1-4, adapted):
```python
from utils.logger import setup_logger
import pandas as pd
import numpy as np

logger = setup_logger(__name__)
```
Note: `from config import config` is NOT needed in `indicators.py` — all parameters are passed as function arguments. The exception is `ORB_MINUTES` default, which uses `config.ORB_MINUTES` as the default value in the function signature — so `config` import IS required there.

**Static method class pattern** (no codebase analog — use RESEARCH.md pattern):
```python
class Indicators:
    """All indicator computations. All methods are @staticmethod — no instance state."""

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_vol = df["Volume"].cumsum()
        cum_tp_vol = (typical * df["Volume"]).cumsum()
        return cum_tp_vol / cum_vol

    @staticmethod
    def ema(df: pd.DataFrame, period: int = 20, column: str = "Close") -> pd.Series:
        return df[column].ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> float:
        high, low, close = df["High"], df["Low"], df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    @staticmethod
    def orb(df: pd.DataFrame, n_minutes: int = None) -> tuple[float, float]:
        from config import config  # late import to avoid circular at module level
        if n_minutes is None:
            n_minutes = config.ORB_MINUTES
        opening_range = df.head(n_minutes)
        return float(opening_range["High"].max()), float(opening_range["Low"].min())

    @staticmethod
    def volume_ratio(df: pd.DataFrame, lookback: int = 20) -> float:
        if len(df) < 2:
            return 0.0
        avg_vol = df["Volume"].iloc[:-1].tail(lookback).mean()
        return float(df["Volume"].iloc[-1] / avg_vol) if avg_vol > 0 else 0.0
```

All excerpts above come directly from `02-RESEARCH.md` §3 — no codebase analog exists; these ARE the reference patterns.

---

### `tests/test_data_layer.py` (test, batch)

**Analog:** None — no test files exist in the codebase.

Use standard pytest conventions. The RESEARCH.md validation architecture (§"Validation Architecture") defines the exact assertions to encode as tests. Structure to follow:

```python
# tests/test_data_layer.py
import pytest
import pandas as pd
from data.universe import get_nse_universe
from data.market_data import MarketDataFetcher
from data.indicators import Indicators


class TestUniverse:
    def test_exactly_100_symbols(self):
        u = get_nse_universe()
        assert len(u) == 100

    def test_all_symbols_end_with_ns(self):
        u = get_nse_universe()
        assert all(s["symbol"].endswith(".NS") for s in u)

    def test_all_have_sector_key(self):
        u = get_nse_universe()
        assert all("sector" in s for s in u)


class TestMarketDataFetcher:
    def test_returns_empty_dataframe_on_bad_symbol(self, fetcher):
        df = fetcher.get_intraday_candles("INVALID_SYMBOL_XYZ.NS")
        assert df is None or df.empty

    def test_returns_none_on_bad_symbol_scalar(self, fetcher):
        result = fetcher.get_previous_close("INVALID_SYMBOL_XYZ.NS")
        assert result is None

    def test_returns_empty_dict_on_failure(self, fetcher, monkeypatch):
        # monkeypatch yf.Ticker to raise — test dict fallback
        pass  # scaffold only in Wave 0


class TestIndicators:
    def test_vwap_returns_series(self, sample_ohlcv):
        result = Indicators.vwap(sample_ohlcv)
        assert isinstance(result, pd.Series)
        assert not result.empty

    def test_rsi_values_in_range(self, sample_ohlcv):
        result = Indicators.rsi(sample_ohlcv)
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_atr_returns_float(self, sample_ohlcv):
        result = Indicators.atr(sample_ohlcv)
        assert isinstance(result, float)
        assert not pd.isna(result)

    def test_orb_returns_tuple(self, sample_ohlcv):
        high, low = Indicators.orb(sample_ohlcv)
        assert high >= low

    def test_volume_ratio_returns_float(self, sample_ohlcv):
        result = Indicators.volume_ratio(sample_ohlcv)
        assert isinstance(result, float)
```

---

### `tests/conftest.py` (config, static-lookup)

**Analog:** None — no test files exist in the codebase.

Pytest fixtures shared across the test suite. Two core fixtures: `fetcher` (MarketDataFetcher instance) and `sample_ohlcv` (deterministic DataFrame for indicator tests — no network required).

```python
# tests/conftest.py
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
    30 rows, session-aligned, no network calls required.
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
```

---

## Shared Patterns

### Import block (applies to ALL new modules except `data/universe.py`)

**Source:** `main.py` lines 1-4
**Apply to:** `data/market_data.py`, `data/indicators.py`

```python
from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)
```

`data/universe.py` is a pure data file — no logger, no config import needed.

---

### Logger level conventions (applies to all service/utility modules)

**Source:** `utils/logger.py` lines 14-30 (level + format definitions)
**Apply to:** `data/market_data.py`, `data/indicators.py`

| Situation | Level |
|---|---|
| Normal operation, fetch attempt | `DEBUG` |
| Empty DataFrame / None returned (possible 429 or delisted) | `WARNING` |
| Exception caught in try/except | `ERROR` |
| Module startup delay disclaimer | `INFO` |

The 15-min delay disclaimer (CONTEXT.md §Specifics) uses `logger.info(...)` at module load — place it at the bottom of `market_data.py`'s module body, outside the class:

```python
# Bottom of data/market_data.py, after class definition
logger.info("yfinance NSE data is 15 minutes delayed — embedded in all trade records.")
```

---

### Error return contract (applies to all MarketDataFetcher methods)

**Source:** CONTEXT.md decisions D-07, D-08, D-09 (no codebase analog)
**Apply to:** Every method in `data/market_data.py`

| Return type | Failure value | Guard callers use |
|---|---|---|
| `float` / scalar | `None` | `if price is None` |
| `pd.DataFrame` | `pd.DataFrame()` | `if df is None or df.empty` |
| `dict` | `{}` | `if not indices` |

Every method wraps its body in `try/except Exception as e:` and returns the appropriate failure value on any exception or empty-DataFrame response from yfinance.

---

### 0.2s rate-limit sleep (applies to all multi-symbol loops)

**Source:** CLAUDE.md §"1. yfinance / Rate Limiting Behavior" + CONTEXT.md D-01
**Apply to:** Any loop over symbols in `data/market_data.py` (e.g., `get_global_indices`)

```python
import time
# Inside any loop that calls yf.Ticker() sequentially:
time.sleep(0.2)
```

---

### Package `__init__.py` pattern

**Source:** `agents/__init__.py`, `data/__init__.py` (both are empty single-line files)
**Apply to:** `tests/__init__.py` if created (keep empty, same convention)

Both existing `__init__.py` files are blank — they exist only to mark the directory as a Python package. No re-exports, no initialization code.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `tests/test_data_layer.py` | test | batch | No test files exist in codebase |
| `tests/conftest.py` | config | static-lookup | No test files exist in codebase |

For these files, use the RESEARCH.md §"Validation Architecture" table as the authoritative test specification, and standard pytest conventions for structure. Code excerpts in the Pattern Assignments section above are derived from research, not codebase analogs.

---

## Metadata

**Analog search scope:** `C:\Users\katuk\OneDrive\Desktop\projects\stockss` (all `.py` files)
**Files scanned:** 7 (config.py, utils/logger.py, main.py, agents/__init__.py, data/__init__.py, execution/__init__.py, utils/__init__.py)
**Pattern extraction date:** 2026-06-06
**Note:** Codebase is early-stage (Phase 1 only). All new data layer files are first-of-their-kind. Shared patterns (import block, logger levels, error returns) are the primary value of this mapping.
