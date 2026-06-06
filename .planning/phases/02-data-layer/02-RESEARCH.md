# Phase 2: Data Layer - Research

**Researched:** 2026-06-06
**Phase:** 02-data-layer

## RESEARCH COMPLETE

---

## 1. yfinance Ticker.history() — correct call pattern for NSE

**For intraday 5-min candles (today):**
```python
ticker = yf.Ticker("RELIANCE.NS")
df = ticker.history(period="1d", interval="5m", prepost=False, auto_adjust=True)
# Returns DataFrame with DatetimeIndex (UTC), columns: Open High Low Close Volume
```

**For previous close / daily historical:**
```python
df = ticker.history(period="5d", interval="1d", prepost=False, auto_adjust=True)
prev_close = df["Close"].iloc[-2]  # [-1] is today if market open
```

**For ATR (14 days daily):**
```python
df = ticker.history(period="30d", interval="1d", prepost=False, auto_adjust=True)
```

**Known issue (CLAUDE.md §yfinance NSE timezone regression):** Some NSE symbols trigger `datetime - str` type error returning empty DataFrame. Must check `if df is None or df.empty` after every call — do not assume non-empty response means valid data.

**Rate limiting:** 0.2s `time.sleep()` between sequential `Ticker()` calls. 429 responses return empty DataFrames silently — same guard covers both failure modes.

---

## 2. NSE timezone handling

yfinance returns UTC timestamps. For session filtering (09:15 IST onward):

```python
import pytz

IST = pytz.timezone("Asia/Kolkata")

def filter_session(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows from 09:15 IST onward."""
    if df.empty:
        return df
    df_ist = df.copy()
    df_ist.index = df_ist.index.tz_convert(IST)
    session_start = df_ist.index[0].replace(hour=9, minute=15, second=0)
    return df_ist[df_ist.index >= session_start]
```

This is done inside `get_intraday_candles()` — callers receive clean session-only data (CONTEXT.md D-05).

---

## 3. Inline pandas indicators — implementation patterns

**VWAP (session-reset):**
```python
def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_vol = df["Volume"].cumsum()
    cum_tp_vol = (typical * df["Volume"]).cumsum()
    return cum_tp_vol / cum_vol
```
VWAP reset is guaranteed by caller passing a session-only DataFrame (D-05).

**EMA:**
```python
def ema(df: pd.DataFrame, period: int = 20, column: str = "Close") -> pd.Series:
    return df[column].ewm(span=period, adjust=False).mean()
```

**RSI:**
```python
def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
```

**ATR (from DataFrame):**
```python
def atr(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]
```

**ORB (opening range breakout):**
```python
def orb(df: pd.DataFrame, n_minutes: int = 15) -> tuple[float, float]:
    opening_range = df.head(n_minutes)  # caller ensures df starts at 09:15
    return opening_range["High"].max(), opening_range["Low"].min()
```

**Volume ratio:**
```python
def volume_ratio(df: pd.DataFrame, lookback: int = 20) -> float:
    if len(df) < 2:
        return 0.0
    avg_vol = df["Volume"].iloc[:-1].tail(lookback).mean()
    return df["Volume"].iloc[-1] / avg_vol if avg_vol > 0 else 0.0
```

All return `float` or `pd.Series`. Callers check for NaN with `pd.isna()` before using values.

---

## 4. Global indices — correct yfinance symbols

| Index | yfinance Symbol |
|-------|----------------|
| S&P 500 | `^GSPC` |
| NASDAQ | `^IXIC` |
| Nikkei 225 | `^N225` |
| Hang Seng | `^HSI` |
| Crude Oil (WTI) | `CL=F` |
| Gold | `GC=F` |
| USD/INR | `USDINR=X` |

`get_global_indices()` fetches latest close for each. Returns `dict[str, float]`. On any single-symbol failure, that key is absent from the dict (partial result acceptable — AgentI0 uses what's available).

---

## 5. NSE universe — Nifty 100 sector breakdown

100 symbols across ~14 sectors. Key large-caps to include:

**Energy/Oil & Gas:** RELIANCE.NS, ONGC.NS, NTPC.NS, POWERGRID.NS, BPCL.NS, IOC.NS, GAIL.NS, COALINDIA.NS
**Financial Services:** HDFCBANK.NS, ICICIBANK.NS, KOTAKBANK.NS, AXISBANK.NS, SBIN.NS, BAJFINANCE.NS, BAJAJFINSV.NS, HDFCLIFE.NS, SBILIFE.NS, SHRIRAMFIN.NS
**IT:** TCS.NS, INFY.NS, HCLTECH.NS, WIPRO.NS, TECHM.NS, LTIM.NS, MPHASIS.NS
**FMCG:** HINDUNILVR.NS, ITC.NS, NESTLEIND.NS, BRITANNIA.NS, DABUR.NS, MARICO.NS, COLPAL.NS, TATACONSUM.NS, GODREJCP.NS
**Auto:** MARUTI.NS, TATAMOTORS.NS, M&M.NS, BAJAJ-AUTO.NS, EICHERMOT.NS, HEROMOTOCO.NS, TVSMOTOR.NS
**Pharma:** SUNPHARMA.NS, DRREDDY.NS, CIPLA.NS, DIVISLAB.NS, APOLLOHOSP.NS, LUPIN.NS, TORNTPHARM.NS, AUROPHARMA.NS
**Metals:** TATASTEEL.NS, JSWSTEEL.NS, HINDALCO.NS, VEDL.NS, SAIL.NS
**Telecom:** BHARTIARTL.NS, INDUSINDBK.NS
**Infra/Capital Goods:** LT.NS, ADANIPORTS.NS, ADANIGREEN.NS, ADANIENT.NS, SIEMENS.NS, ABB.NS, BEL.NS
**Cement:** ULTRACEMCO.NS, GRASIM.NS, AMBUJACEM.NS, ACC.NS, SHREECEM.NS
**Consumer Durables:** TITAN.NS, HAVELLS.NS, VOLTAS.NS, WHIRLPOOL.NS
**Chemicals:** PIDILITIND.NS, ASIANPAINT.NS, BERGERPAINTS.NS
**Media/Realty:** ZOMATO.NS, NYKAA.NS, PAYTM.NS, DLF.NS, GODREJPROP.NS, OBEROIRLTY.NS
**Others:** INDIGO.NS, TRENT.NS, DMART.NS, MOTHERSON.NS, MRF.NS, BALKRISIND.NS, BOSCHLTD.NS, CGPOWER.NS, CUMMINSIND.NS, HDFCAMC.NS, ICICIGI.NS, MUTHOOTFIN.NS, PFC.NS, RECLTD.NS, ZYDUSLIFE.NS

Total: 100 symbols. All end in `.NS`. Each gets a `sector` tag from the list above.

---

## 6. get_atr() in MarketDataFetcher vs Indicators.atr()

**D-11 split confirmed:**

`MarketDataFetcher.get_atr(symbol, period=14)`:
- Fetches 30 days daily OHLCV internally via `Ticker.history(period="30d", interval="1d")`
- Returns `float` — latest ATR value
- Used by AgentI3 at watchlist build time (pre-market, no live DataFrame available)

`Indicators.atr(df, period=14)`:
- Receives caller-supplied DataFrame
- Returns `float` — latest ATR from that DataFrame
- Used by AgentI4/I6 during session (live intraday or daily DataFrame already fetched)

---

## Validation Architecture

| Success Criterion | Test |
|-------------------|------|
| MarketDataFetcher returns shaped OHLCV for RELIANCE.NS | `python -c "from data.market_data import MarketDataFetcher; f=MarketDataFetcher(); df=f.get_intraday_candles('RELIANCE.NS'); print(df.shape, list(df.columns))"` |
| Returns None/empty on bad symbol without raising | `python -c "from data.market_data import MarketDataFetcher; f=MarketDataFetcher(); assert f.get_previous_close('INVALID.NS') is None"` |
| All 7 global indices non-null on market day | `python -c "from data.market_data import MarketDataFetcher; f=MarketDataFetcher(); d=f.get_global_indices(); print(d)"` |
| All 6 indicator methods produce float/Series on valid df | Manual test with RELIANCE.NS intraday data |
| VWAP resets at 09:15 | Index of returned VWAP starts at 09:15 IST |
| NSE universe = 100 symbols all .NS | `python -c "from data.universe import get_nse_universe; u=get_nse_universe(); assert len(u)==100; assert all(s['symbol'].endswith('.NS') for s in u)"` |
| No ta imports anywhere | `grep -r "import ta" data/` returns nothing |
