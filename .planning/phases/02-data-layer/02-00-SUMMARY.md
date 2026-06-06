---
phase: "02-data-layer"
plan: "00"
subsystem: "test-scaffold"
tags: ["testing", "pytest", "fixtures", "tdd", "wave-0"]
dependency_graph:
  requires: []
  provides: ["tests/__init__.py", "tests/conftest.py", "tests/test_data_layer.py"]
  affects: ["02-01-PLAN.md", "02-02-PLAN.md"]
tech_stack:
  added: []
  patterns: ["pytest fixtures", "deterministic synthetic data", "RED state stub tests"]
key_files:
  created:
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_data_layer.py
  modified: []
decisions:
  - "Stub tests use ImportError-on-collection as RED state signal (no data modules exist yet)"
  - "sample_ohlcv fixture uses np.random.seed(42) for deterministic, reproducible test data"
  - "fetcher fixture is module-scoped to share single MarketDataFetcher instance across tests"
metrics:
  duration: "5 minutes"
  completed: "2026-06-06"
  tasks_completed: 2
  files_created: 3
---

# Phase 2 Plan 00: Test Scaffold Summary

**One-liner:** Pytest test scaffold with deterministic OHLCV fixtures and 15 RED-state stub tests covering DATA-01 through DATA-15.

## What Was Built

- `tests/__init__.py` — Empty package marker
- `tests/conftest.py` — Two pytest fixtures: `fetcher` (module-scoped MarketDataFetcher instance) and `sample_ohlcv` (deterministic 30-row DataFrame using np.random.seed(42), no network calls)
- `tests/test_data_layer.py` — 15 stub test functions organized in 3 classes:
  - `TestUniverse` (3 tests): universe_count, universe_format, universe_no_duplicates
  - `TestMarketDataFetcher` (7 tests): bad symbol, prepost, rate limit, scalar None, session filter, global indices partial, ATR None
  - `TestIndicators` (6 tests): vwap_no_nan, ema_output_shape, rsi_bounds, indicators_atr_returns_float, orb_tuple, volume_ratio_insufficient_data

## RED State Verification

`pytest tests/test_data_layer.py --collect-only` → `ModuleNotFoundError: No module named 'data.market_data'` — correct RED behavior.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- tests/__init__.py: EXISTS
- tests/conftest.py: EXISTS, syntax valid
- tests/test_data_layer.py: EXISTS, syntax valid, 15 test functions
- Commit f694a23: EXISTS
