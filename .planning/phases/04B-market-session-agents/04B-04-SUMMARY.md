---
phase: 04B-market-session-agents
plan: 04
type: summary
status: complete
date: 2026-06-07
---

# Summary: Phase 4B-04 — Test Suite for AgentI4 + AgentI6

## Outcome
All 44 tests pass (28 for AgentI4, 16 for AgentI6).

## Files Created
- `tests/test_agent_i6.py` — 16 tests covering AGNT-12
- `tests/test_agent_i4.py` — 28 tests covering AGNT-09, AGNT-10, AGNT-11
- `tests/helpers.py` — shared helpers: make_candles(), make_entry(), mock_portfolio_factory()

## Key Decisions

### Circuit detection test (test_agent_i6.py)
Uses price=1490.0 (below partial-exit threshold 1495 and trailing SL threshold 1500) with `_get_position.return_value = None` so only circuit logic runs. Three separate `monitor_positions` calls simulate three polling cycles — the deque accumulates one price per call (not per row in the DataFrame).

### AgentI4 mock pattern
- `portfolio._get_position` is a MagicMock attribute; set `.return_value = pos` (dict) or `= None` to control trailing SL path.
- `yf.download` and `time.sleep` patched via `@patch("agents.agent_i4.yf.download")` / `@patch("agents.agent_i4.time.sleep")` — no live network calls.

### Windows→Linux mount mtime issue
The Edit tool writes via Windows; the Linux VM's FS cache keeps stale mtime and stale content. Resolution: always write test files directly from bash (`cat > file << 'PYEOF'`) so the VM has current content and pytest picks up the updated source.

## Test Coverage

| Class | Tests | What's Verified |
|---|---|---|
| TestCircuitDetection | 2 | 3-cycle identical price → circuit_set; circuit skip prevents sell |
| TestHardExits | 3 | SL_HIT, TARGET_HIT, normal price (no sell) |
| TestPartialExits | 5 | GAP_AND_GO/ORB_BREAKOUT fire; already-done guard; GAP_FILL/VWAP_RECLAIM skip |
| TestTrailingStopLoss | 6 | Trail fires, threshold guard, no-downgrade guard, ORB breakeven, fixed SL |
| TestInit | 3 | watchlist_map keying, initial flags, AgentI6 monitor |
| TestFetchBatch | 4 | Empty input, sleep guard, single ticker, empty download |
| TestOrbOverride | 4 | Time gate, fires at 09:30, once-only guard, entry_trigger update |
| TestForceSquareoff | 4 | Sell per position, current_prices used, entry_price fallback, idempotency |
| TestCheckEntriesTimeGates | 4 | Before 09:30, after 14:00, at 09:30, at 14:00 |
| TestCheckEntriesSignals | 6 | All 4 strategies correct direction + negative cases |
| TestCheckEntriesSymbolHandling | 3 | Symbol removed on buy, retained on fail, circuit skip |
