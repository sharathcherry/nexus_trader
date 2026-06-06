---
phase: "02-data-layer"
plan: "02"
subsystem: "indicators"
tags: ["indicators", "vwap", "ema", "rsi", "atr", "orb", "volume-ratio", "pandas", "numpy"]
dependency_graph:
  requires: ["02-00"]
  provides: ["data/indicators.py"]
  affects: ["AgentI4 (signal engine)", "AgentI6 (position monitor)"]
tech_stack:
  added: []
  patterns: ["staticmethod-class", "inline-pandas-indicators", "late-import-config"]
key_files:
  created:
    - data/indicators.py
  modified: []
decisions:
  - "All 6 methods are @staticmethod — no instance state, callers pass DataFrames directly"
  - "atr() returns 0.0 (not NaN, not raises) on short DataFrame — safe sentinel value"
  - "orb() uses late import for config.ORB_MINUTES to avoid circular import at module level"
  - "rsi() protects against division-by-zero using loss.replace(0, float('nan'))"
metrics:
  duration: "5 minutes"
  completed: "2026-06-06"
  tasks_completed: 2
  files_created: 1
---

# Phase 2 Plan 02: Indicators Summary

**One-liner:** Stateless Indicators class with 6 @staticmethod methods (VWAP, EMA, RSI, ATR, ORB, volume_ratio) implemented inline with pandas/numpy — no ta library dependency.

## What Was Built

- `data/indicators.py`: `Indicators` class with 6 @staticmethod methods:
  - `vwap(df)`: Session-reset cumulative VWAP, no NaN on valid non-zero-volume OHLCV
  - `ema(df, period, column)`: ewm(span=period, adjust=False).mean()
  - `rsi(df, period)`: Rolling gain/loss RSI, divide-by-zero protected, NaN prefix rows normal
  - `atr(df, period)`: True Range rolling mean, returns 0.0 on short DataFrame
  - `orb(df, n_minutes)`: First N minutes opening range (high, low), returns (0.0, 0.0) on empty
  - `volume_ratio(df, lookback)`: Current bar / avg preceding bars, returns 0.0 on <2 rows

## Test Results

- TestIndicators::test_vwap_no_nan: PASSED
- TestIndicators::test_ema_output_shape: PASSED
- TestIndicators::test_rsi_bounds: PASSED
- TestIndicators::test_indicators_atr_returns_float: PASSED
- TestIndicators::test_orb_tuple: PASSED
- TestIndicators::test_volume_ratio_insufficient_data: PASSED

All 6 TestIndicators tests GREEN. No ta library imports confirmed.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- data/indicators.py: EXISTS
- All 6 @staticmethod methods verified with seed-42 deterministic data
- Commit 1e58c6c: EXISTS
- grep "import ta" data/indicators.py: NO MATCH
