---
phase: 2
slug: data-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-06
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | tests/conftest.py — Wave 0 installs |
| **Quick run command** | `pytest tests/test_data_layer.py -x -q` |
| **Full suite command** | `pytest tests/test_data_layer.py -v` |
| **Estimated runtime** | ~30 seconds (network calls mocked) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_data_layer.py -x -q`
- **After every plan wave:** Run `pytest tests/test_data_layer.py -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | DATA-01 | — | Empty DF on bad symbol, no exception raised | unit | `pytest tests/test_data_layer.py::test_intraday_candles_bad_symbol -x -q` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | DATA-02 | — | prepost=False on all calls | unit | `pytest tests/test_data_layer.py::test_prepost_false -x -q` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | DATA-03 | — | 0.2s sleep between calls observable | unit | `pytest tests/test_data_layer.py::test_rate_limit_delay -x -q` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | DATA-04 | — | get_previous_close returns None on failure | unit | `pytest tests/test_data_layer.py::test_scalar_returns_none_on_failure -x -q` | ❌ W0 | ⬜ pending |
| 02-01-05 | 01 | 1 | DATA-05 | — | get_intraday_candles rows start >= 09:15 IST | unit | `pytest tests/test_data_layer.py::test_session_filter_09_15 -x -q` | ❌ W0 | ⬜ pending |
| 02-01-06 | 01 | 1 | DATA-06 | — | get_global_indices returns partial dict on single failure | unit | `pytest tests/test_data_layer.py::test_global_indices_partial -x -q` | ❌ W0 | ⬜ pending |
| 02-01-07 | 01 | 1 | DATA-07 | — | get_atr returns float, fetches 30d daily internally | unit | `pytest tests/test_data_layer.py::test_get_atr_fetcher -x -q` | ❌ W0 | ⬜ pending |
| 02-01-08 | 01 | 1 | DATA-01 | — | NSE universe = exactly 100 symbols | unit | `pytest tests/test_data_layer.py::test_universe_count -x -q` | ❌ W0 | ⬜ pending |
| 02-01-09 | 01 | 1 | DATA-01 | — | All symbols end in .NS with sector tag | unit | `pytest tests/test_data_layer.py::test_universe_format -x -q` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | DATA-10 | — | VWAP cumulative from first row, no NaN on valid df | unit | `pytest tests/test_data_layer.py::test_vwap_no_nan -x -q` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | DATA-11 | — | EMA returns Series same length as input | unit | `pytest tests/test_data_layer.py::test_ema_output_shape -x -q` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 1 | DATA-12 | — | RSI values bounded [0, 100] | unit | `pytest tests/test_data_layer.py::test_rsi_bounds -x -q` | ❌ W0 | ⬜ pending |
| 02-02-04 | 02 | 1 | DATA-13 | — | ATR returns float on valid df | unit | `pytest tests/test_data_layer.py::test_indicators_atr_returns_float -x -q` | ❌ W0 | ⬜ pending |
| 02-02-05 | 02 | 1 | DATA-14 | — | ORB returns (high, low) tuple, high >= low | unit | `pytest tests/test_data_layer.py::test_orb_tuple -x -q` | ❌ W0 | ⬜ pending |
| 02-02-06 | 02 | 1 | DATA-15 | — | volume_ratio returns 0.0 when insufficient rows | unit | `pytest tests/test_data_layer.py::test_volume_ratio_insufficient_data -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_data_layer.py` — stubs for DATA-01 through DATA-15 (all RED initially)
- [ ] `tests/conftest.py` — shared fixtures: synthetic OHLCV DataFrame, mock yfinance Ticker

*pytest is already in requirements.txt from Phase 1.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 0.2s inter-call delay visible in timing logs | DATA-03 | Network timing varies; CI environment has no real yfinance calls | Run `python -c "from data.market_data import MarketDataFetcher; f=MarketDataFetcher(); f.get_global_indices()"` and check logs show ~0.2s gaps |
| All 7 global indices non-null on a live market day | DATA-06 | Requires live network + open market | Run manually on a trading day: `python -c "from data.market_data import MarketDataFetcher; f=MarketDataFetcher(); d=f.get_global_indices(); print(d)"` |
| No ta imports anywhere in data module | DATA-15 | Grep check, not test | `grep -r "import ta" data/` must return nothing |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
