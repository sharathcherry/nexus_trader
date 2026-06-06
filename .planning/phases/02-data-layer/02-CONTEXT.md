# Phase 2: Data Layer - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning

<domain>
## Phase Boundary

All market data and indicator computations are available, guarded, and tested with known inputs — the foundation every agent depends on. Delivers `data/market_data.py` (MarketDataFetcher), `data/indicators.py` (Indicators), and `data/universe.py` (NSE 100 list). No agent logic, no portfolio math, no scheduling.

</domain>

<decisions>
## Implementation Decisions

### yfinance fetch pattern
- **D-01:** Individual `Ticker.history()` calls with 0.2s `time.sleep()` between calls — no `yf.download()`. Avoids MultiIndex column flattening hazard documented in CLAUDE.md. All methods use the pattern: `yf.Ticker(symbol).history(...)` and return a single-level DataFrame directly.
- **D-02:** `prepost=False` and `auto_adjust=True` (default) on all yfinance calls. Pre-open indicative candles (09:00–09:15) are excluded.

### NSE universe storage
- **D-03:** Hardcoded Python list in `data/universe.py` — list of dicts: `[{"symbol": "RELIANCE.NS", "sector": "Energy"}, ...]`. Zero file I/O at startup, version-controlled, grep-friendly. `get_nse_universe()` returns this list. Manual update when Nifty 100 constituents change (~quarterly).
- **D-04:** Exactly 100 symbols, all ending in `.NS`, each with a `sector` key. Sectors: Energy, Financial Services, IT, FMCG, Auto, Pharma, Metals, Telecom, Infra, Cement, Consumer Durables, Chemicals, Media, Realty.

### Indicator input contract
- **D-05:** Caller is responsible for filtering — `MarketDataFetcher.get_intraday_candles()` returns only rows from 09:15 IST onward. Indicators methods receive a clean, session-only DataFrame and never perform timestamp filtering internally. VWAP reset is implicit: the DataFrame starts at 09:15, so cumulative VWAP is always session-scoped.
- **D-06:** ORB window (DATA-14) uses `n_minutes` parameter defaulting to `config.ORB_MINUTES` (15 minutes). Returns `(orb_high, orb_low)` tuple. Caller slices first N rows of the session DataFrame.

### Error return contract
- **D-07:** Scalar methods (`get_previous_close`, `get_premarket_price`, `get_atr`) return `None` on failure.
- **D-08:** Tabular methods (`get_intraday_candles`, `get_historical_data`) return empty `pd.DataFrame()` on failure.
- **D-09:** Dict/multi-value methods (`get_global_indices`) return empty `{}` on failure.
- **D-10:** All agents check with: `if price is None` for scalars, `if df is None or df.empty` for DataFrames, `if not indices` for dicts. No exceptions are raised by fetcher methods — try/except is internal.

### ATR split (DATA-07 vs DATA-13)
- **D-11:** Two distinct ATR functions with different inputs. `MarketDataFetcher.get_atr(symbol, period=14)` fetches daily OHLCV internally and returns a single float (used at watchlist build time). `Indicators.atr(df)` computes ATR from a caller-supplied DataFrame and returns the latest value (used by position monitor during session). Both use pandas rolling — no `ta` library.

### Claude's Discretion
- Exact rolling window implementation for EMA (`.ewm(span=period)` vs manual)
- Whether `Indicators` methods are `@staticmethod` or `@classmethod`
- Log message format for 429 / empty DataFrame responses from yfinance

</decisions>

<specifics>
## Specific Ideas

- Success criterion: `MarketDataFetcher` returns correctly shaped OHLCV DataFrame for `RELIANCE.NS` and returns `None`/empty without raising on bad symbol or network failure.
- Success criterion: All 7 global indices non-null on a market day; 0.2s inter-call delay observable in timing logs.
- Success criterion: All 6 indicator methods produce float outputs (no NaN) on valid intraday DataFrame; VWAP resets at 09:15.
- Success criterion: NSE universe contains exactly 100 symbols, all `.NS`, with sector tags; no `ta` imports anywhere in data module.
- 15-min NSE data delay must be logged at module init — one INFO line at startup: "yfinance NSE data is 15 minutes delayed — embedded in all trade records."

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### yfinance behavior and hazards
- `CLAUDE.md` §"1. yfinance" — breaking changes in 0.2.x, MultiIndex columns issue, rate limiting 429 behavior, NSE timezone regression, `prepost=False` default, version pin rationale
- `CLAUDE.md` §"1. yfinance / NSE (.NS) Specific Issues" — symbol-specific gotchas

### Architecture decisions (locked)
- `.planning/STATE.md` §"Key Decisions Made" — `ta` exclusion, `prepost=False`, inline pandas indicators, 15-min delay documentation, 0.2s rate limiting
- `.planning/phases/01-foundation/01-CONTEXT.md` — import patterns, package structure, logger setup

### Requirements
- `.planning/REQUIREMENTS.md` §"Data Layer" (DATA-01 through DATA-15) — complete requirement set for this phase
- `.planning/ROADMAP.md` §"Phase 2: Data Layer" — success criteria (4 items) that define done

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `config.py` (from Phase 1) — `config.ORB_MINUTES`, `config.CAPITAL`, all trading parameters available via `from config import config`
- `utils/logger.py` (from Phase 1) — `setup_logger(__name__)` used at module top in `market_data.py` and `indicators.py`

### Established Patterns
- Import pattern: `from config import config` (established Phase 1)
- Logger pattern: `logger = setup_logger(__name__)` at module level
- No `ta` library anywhere — inline pandas only

### Integration Points
- `data/market_data.py` → feeds every agent in Phase 4a/4b/4c
- `data/indicators.py` → called by AgentI4 (signal engine) each polling cycle
- `data/universe.py` → used by AgentI1 (gap screener) and Phase 6 backtester
- `MarketDataFetcher.get_atr()` → used by AgentI3 for stop/target calculation
- `MarketDataFetcher.get_historical_data()` → used by Phase 6 NexusBacktester

</code_context>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-data-layer*
*Context gathered: 2026-06-06*
