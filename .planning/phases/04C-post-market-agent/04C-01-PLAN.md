---
phase: 04C
plan: 01
type: tdd
wave: 1
depends_on: []
files_modified:
  - tests/__init__.py
  - tests/conftest.py
  - tests/test_agent_i9.py
autonomous: true
requirements:
  - AGNT-13
  - AGNT-14
  - AGNT-15
  - AGNT-16

must_haves:
  truths:
    - "All 10 test cases in test_agent_i9.py exist and are collected by pytest"
    - "conftest.py provides a mock anthropic client fixture, an in-memory SQLite fixture with trades rows, and a tmp_path-scoped perf_dir fixture"
    - "Every test case fails (RED) before agents/agent_i9.py exists — proving tests are meaningful assertions, not no-ops"
    - "pytest tests/test_agent_i9.py -x --collect-only lists all 10 test IDs without import error"
  artifacts:
    - path: "tests/__init__.py"
      provides: "makes tests/ a package so pytest discovers it"
    - path: "tests/conftest.py"
      provides: "shared fixtures: mock_stream, in_memory_db, perf_dir"
    - path: "tests/test_agent_i9.py"
      provides: "10 test functions covering AGNT-13 through AGNT-16"
  key_links:
    - from: "tests/conftest.py"
      to: "tests/test_agent_i9.py"
      via: "pytest fixture injection"
      pattern: "def mock_stream|def in_memory_db|def perf_dir"
    - from: "tests/test_agent_i9.py"
      to: "agents/agent_i9.py"
      via: "import AgentI9, DailyReview, ParameterChange"
      pattern: "from agents.agent_i9 import"
---

<objective>
Create the test scaffold for AgentI9 — all fixtures and test cases — before the implementation exists. Tests must fail (RED) immediately after creation, proving they are real assertions.

Purpose: TDD gate ensures agents/agent_i9.py implements every AGNT-13 through AGNT-16 requirement exactly as specified rather than doing the minimum to avoid assertion errors.
Output: tests/__init__.py, tests/conftest.py, tests/test_agent_i9.py — 10 test cases, all RED.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/04C-post-market-agent/04C-CONTEXT.md
@.planning/phases/04C-post-market-agent/04C-RESEARCH.md
@.planning/phases/04C-post-market-agent/04C-PATTERNS.md

<interfaces>
<!-- Key types AgentI9 will expose — executor must write tests against these exact signatures. -->
<!-- These will not exist yet; tests import them and fail (RED). -->

From agents/agent_i9.py (to be created in Plan 02):
```python
class ParameterChange(BaseModel):
    param_name: str
    current_value: float
    suggested_value: float
    reason: str

class DailyReview(BaseModel):
    session_verdict: str               # "PROFITABLE" / "BREAKEVEN" / "LOSS"
    winning_strategies: list[str]
    underperforming_strategies: list[str]
    parameter_adjustments: list[ParameterChange]
    tomorrow_watch: list[str]
    summary: str

class AgentI9:
    def __init__(self, portfolio: PaperPortfolio) -> None: ...
    def run(self) -> DailyReview | None: ...
    # private helpers (testable via patch):
    def _get_rolling_stats(self, days: int = 20) -> dict: ...
    def _estimate_tokens(self, text: str) -> int: ...
    def _validate_parameter_adjustments(self, adjustments: list[ParameterChange]) -> list[ParameterChange]: ...
    def _build_prompt(self, today_trades: list[dict], rolling_stats: dict, omit_times: bool = False) -> str: ...
    def _print_summary(self, review: DailyReview | None, state: str, today_str: str, today_trades: list[dict]) -> None: ...
```

From config.py (verified):
```python
config.MAX_OPEN_POSITIONS = 5       # int
config.MIN_RISK_REWARD = 1.5        # float
config.RISK_PER_TRADE_PCT = 0.01    # float (decimal; 1% as 0.01)
config.ANTHROPIC_API_KEY = "..."    # str from .env
```

trades table schema (Phase 3, per 04C-CONTEXT.md canonical_refs):
columns: symbol, entry_price, exit_price, qty, strategy, entry_time, exit_time, gross_pnl, brokerage, net_pnl, exit_reason
</interfaces>
</context>

<tasks>

<task type="tdd">
  <name>Task 1: Write conftest.py with shared fixtures (RED)</name>
  <files>tests/__init__.py, tests/conftest.py</files>
  <read_first>
    - .planning/phases/04C-post-market-agent/04C-RESEARCH.md (Validation Architecture section — fixture list, Wave 0 gaps)
    - .planning/phases/04C-post-market-agent/04C-PATTERNS.md (SQLite query pattern, anthropic streaming pattern)
    - config.py (attribute names: ANTHROPIC_API_KEY, MAX_OPEN_POSITIONS, MIN_RISK_REWARD, RISK_PER_TRADE_PCT)
    - utils/logger.py (setup_logger pattern — conftest must not import logger at module level)
  </read_first>
  <behavior>
    - Fixture `mock_portfolio`: returns a MagicMock with `get_daily_report()` returning a list of 2 trade dicts, each with keys: symbol, strategy, entry_price, exit_price, qty, gross_pnl, brokerage, net_pnl, exit_reason, entry_time, exit_time
    - Fixture `in_memory_db`: creates an in-memory SQLite DB, creates `trades` table with all 11 columns, inserts 5 rows with exit_time = today (2 strategies: GAP_AND_GO x3, VWAP_RECLAIM x2), net_pnl values mix of positive and negative; returns the DB file path (tmp_path based so isolated per test)
    - Fixture `perf_dir`: uses tmp_path to create a temporary logs/performance directory, monkeypatches `agents.agent_i9.PERF_DIR` to point to it (once agent_i9 exists); returns the Path
    - Fixture `mock_stream_success`: returns a context manager mock that yields a stream object; `stream.text_stream` yields a single valid JSON string matching DailyReview schema; `stream.get_final_message()` returns a mock with `usage.input_tokens=500, usage.output_tokens=200`
    - Fixture `mock_stream_bad_json`: same context manager structure but `stream.text_stream` yields `"not valid json {{"` to trigger JSONDecodeError
    - Fixture `mock_stream_exception`: calling `__enter__` raises `anthropic.APIConnectionError`
    - `tests/__init__.py` is empty (just creates the package)
  </behavior>
  <action>
    Create tests/__init__.py as an empty file.

    Create tests/conftest.py with imports: pytest, sqlite3, json, datetime, pathlib.Path, unittest.mock (MagicMock, patch, MagicMock as contextmanager mock).

    mock_portfolio fixture: scope="function". Return a MagicMock. Configure get_daily_report() return value as a list of 2 dicts: [{"symbol": "RELIANCE.NS", "strategy": "GAP_AND_GO", "entry_price": 2850.0, "exit_price": 2920.0, "qty": 3, "gross_pnl": 210.0, "brokerage": 40.0, "net_pnl": 170.0, "exit_reason": "TARGET_HIT", "entry_time": "2026-06-06 09:35:00", "exit_time": "2026-06-06 11:22:00"}, {"symbol": "TCS.NS", "strategy": "VWAP_RECLAIM", "entry_price": 3500.0, "exit_price": 3460.0, "qty": 2, "gross_pnl": -80.0, "brokerage": 20.0, "net_pnl": -100.0, "exit_reason": "SL_HIT", "entry_time": "2026-06-06 10:05:00", "exit_time": "2026-06-06 12:30:00"}].

    in_memory_db fixture: scope="function", uses tmp_path. Create file at tmp_path / "portfolio.db". Open with sqlite3.connect(). Create trades table: CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, entry_price REAL, exit_price REAL, qty INTEGER, strategy TEXT, entry_time TEXT, exit_time TEXT, gross_pnl REAL, brokerage REAL, net_pnl REAL, exit_reason TEXT). Insert 5 rows — 3 GAP_AND_GO (net_pnl 150.0, 200.0, -50.0) and 2 VWAP_RECLAIM (net_pnl 80.0, -120.0) — all with exit_time = datetime.date.today().isoformat() + " 12:00:00". Commit, close. Return the db file Path.

    perf_dir fixture: scope="function", uses tmp_path. Create directory tmp_path / "performance". Return the Path (monkeypatching PERF_DIR happens in individual tests to avoid import-time coupling).

    mock_stream_success fixture: scope="function". Build a valid DailyReview JSON string: {"session_verdict": "PROFITABLE", "winning_strategies": ["GAP_AND_GO"], "underperforming_strategies": ["VWAP_RECLAIM"], "parameter_adjustments": [], "tomorrow_watch": ["RELIANCE.NS"], "summary": "Good session."}. Create a MagicMock for the stream object. Configure stream.text_stream as [valid_json_str] (list, iterator). Configure stream.get_final_message() to return a MagicMock with usage.input_tokens=500, usage.output_tokens=200. Create a MagicMock context manager: __enter__ returns stream, __exit__ returns False. Return the context manager mock.

    mock_stream_bad_json fixture: same structure but text_stream yields "not-valid-json{{".

    mock_stream_exception fixture: MagicMock where __enter__ raises anthropic.APIConnectionError (import anthropic in conftest).
  </action>
  <verify>
    <automated>cd C:/Users/katuk/OneDrive/Desktop/projects/stockss && python -m pytest tests/conftest.py --collect-only -q 2>&1 | head -20</automated>
  </verify>
  <done>tests/__init__.py exists (empty). tests/conftest.py exists with 6 fixtures: mock_portfolio, in_memory_db, perf_dir, mock_stream_success, mock_stream_bad_json, mock_stream_exception. No import errors when pytest collects conftest.</done>
  <acceptance_criteria>
    - `python -c "import tests.conftest"` exits 0 (or test collection succeeds without ImportError)
    - tests/conftest.py contains the string "mock_portfolio" (fixture name)
    - tests/conftest.py contains the string "in_memory_db" (fixture name)
    - tests/conftest.py contains the string "mock_stream_success" (fixture name)
    - tests/conftest.py contains "CREATE TABLE" and "trades" (in_memory_db creates the schema)
    - tests/__init__.py exists and is empty or near-empty
  </acceptance_criteria>
</task>

<task type="tdd">
  <name>Task 2: Write test_agent_i9.py — all 10 test cases (RED)</name>
  <files>tests/test_agent_i9.py</files>
  <read_first>
    - tests/conftest.py (fixtures just created — know exact fixture names and return types)
    - .planning/phases/04C-post-market-agent/04C-RESEARCH.md (Validation Architecture section: Req ID → test map, all 10 test IDs listed)
    - .planning/phases/04C-post-market-agent/04C-CONTEXT.md (D-07 rejection rules, D-04 three output states, D-05 tabulate in all states, D-10 token cap truncation)
    - .planning/phases/04C-post-market-agent/04C-PATTERNS.md (_validate_parameter_adjustments pattern, _estimate_tokens pattern)
    - config.py (config.MAX_OPEN_POSITIONS=5, config.MIN_RISK_REWARD=1.5, config.RISK_PER_TRADE_PCT=0.01)
  </read_first>
  <behavior>
    AGNT-13 — test_prompt_construction:
      Given mock_portfolio.get_daily_report() returns 2 trades and in_memory_db has 5 trades,
      when AgentI9(mock_portfolio)._build_prompt(today_trades, rolling_stats) is called,
      then the returned string contains "GAP_AND_GO", contains "RELIANCE.NS", contains "1.0%" (RISK_PER_TRADE_PCT in percentage form), and len(result) > 100

    AGNT-13 — test_token_cap_truncation:
      Given _build_prompt returns a string of length 44,001 chars (= 11,000 estimated tokens),
      when run() is called (stream mocked to avoid actual API call),
      then at least one WARNING log message was emitted containing "truncated" before the stream is called

    AGNT-14 — test_parse_valid_response:
      Given mock_stream_success yields valid DailyReview JSON,
      when AgentI9(mock_portfolio).run() is called with PERF_DIR monkeypatched,
      then return value is a DailyReview instance with session_verdict == "PROFITABLE" and winning_strategies == ["GAP_AND_GO"]

    AGNT-14 — test_partial_response_saved:
      Given mock_stream_bad_json yields malformed JSON,
      when run() completes,
      then review_partial_YYYYMMDD.json exists in perf_dir AND review_failed_YYYYMMDD.json exists in perf_dir AND run() returns None

    AGNT-15 — test_reject_max_positions:
      Given _validate_parameter_adjustments is called with [ParameterChange(param_name="MAX_OPEN_POSITIONS", current_value=5.0, suggested_value=7.0, reason="test")],
      then the returned list is empty (suggestion rejected) AND a WARNING was logged containing "MAX_OPEN_POSITIONS"

    AGNT-15 — test_reject_min_rr:
      Given _validate_parameter_adjustments with [ParameterChange(param_name="MIN_RISK_REWARD", current_value=1.5, suggested_value=1.2, reason="test")],
      then returned list is empty AND WARNING logged containing "MIN_RISK_REWARD"

    AGNT-15 — test_reject_risk_pct:
      Given _validate_parameter_adjustments with [ParameterChange(param_name="RISK_PER_TRADE_PCT", current_value=1.0, suggested_value=2.0, reason="test")],
      then returned list is empty AND WARNING logged containing "RISK_PER_TRADE_PCT"

    AGNT-16 — test_output_file_success:
      Given mock_stream_success, perf_dir monkeypatched,
      when run() completes,
      then file perf_dir / f"review_{today_str}.json" exists AND its content parses as valid JSON with key "session_verdict" == "PROFITABLE" AND no review_failed file exists

    AGNT-16 — test_output_file_failure:
      Given mock_stream_exception raises APIConnectionError,
      when run() completes,
      then review_failed_YYYYMMDD.json exists in perf_dir AND its content is valid JSON with key "error" AND run() returns None AND no review_YYYYMMDD.json (success file) exists

    AGNT-16 — test_terminal_summary:
      Given mock_stream_success, when run() completes,
      then _print_summary was called (or capsys captured output containing "Verdict:" or "PROFITABLE")
      For failure state: given mock_stream_exception, capsys contains "Review generation failed"
  </behavior>
  <action>
    Create tests/test_agent_i9.py.

    Imports: pytest, json, datetime.date, pathlib.Path, unittest.mock (patch, MagicMock), io.StringIO.

    Import pattern at top: `from agents.agent_i9 import AgentI9, DailyReview, ParameterChange` — this import will cause ImportError (file does not exist), making ALL tests RED immediately. That is the expected TDD state.

    Also import: `from config import config`.

    today_str helper at module level: `TODAY = date.today().strftime("%Y%m%d")`.

    test_prompt_construction: Instantiate AgentI9 with mock_portfolio (patch self._client so Anthropic() does not require real key). Call _build_prompt() with the trade list from conftest and a sample rolling_stats dict. Assert: "GAP_AND_GO" in result, "RELIANCE.NS" in result, "1.0%" in result (per D-07 RISK_PER_TRADE_PCT percentage form).

    test_token_cap_truncation: Patch AgentI9._build_prompt to return "x" * 44_001 on first call and "y" * 100 on subsequent calls. Patch self._client.messages.stream with mock_stream_success. Use caplog to capture WARNING messages. Call run(). Assert any WARNING record contains "truncated".

    test_parse_valid_response: Create AgentI9 instance (patch Anthropic client). Patch self._client.messages.stream with mock_stream_success. Patch agents.agent_i9.PERF_DIR to perf_dir. Patch agents.agent_i9.DB_PATH to in_memory_db path. Call run(). Assert result is DailyReview. Assert result.session_verdict == "PROFITABLE".

    test_partial_response_saved: Patch stream with mock_stream_bad_json. Patch PERF_DIR to perf_dir. Call run(). Assert (perf_dir / f"review_partial_{TODAY}.json").exists(). Assert (perf_dir / f"review_failed_{TODAY}.json").exists(). Assert result is None.

    test_reject_max_positions: Create AgentI9 instance (patch client). Call _validate_parameter_adjustments([ParameterChange(param_name="MAX_OPEN_POSITIONS", current_value=5.0, suggested_value=7.0, reason="raises limit")]). Assert returned list == []. Assert caplog has WARNING with "MAX_OPEN_POSITIONS".

    test_reject_min_rr: Same pattern, param_name="MIN_RISK_REWARD", suggested_value=1.2. Assert list empty, WARNING contains "MIN_RISK_REWARD".

    test_reject_risk_pct: param_name="RISK_PER_TRADE_PCT", suggested_value=2.0 (percentage form, 2.0 > 1.5 threshold). Assert list empty, WARNING contains "RISK_PER_TRADE_PCT".

    test_output_file_success: Patch stream with mock_stream_success. Patch PERF_DIR and DB_PATH. Call run(). success_file = perf_dir / f"review_{TODAY}.json". Assert success_file.exists(). Assert json.loads(success_file.read_text())["session_verdict"] == "PROFITABLE". Assert not (perf_dir / f"review_failed_{TODAY}.json").exists().

    test_output_file_failure: Patch stream with mock_stream_exception. Patch PERF_DIR. Call run(). failed_file = perf_dir / f"review_failed_{TODAY}.json". Assert failed_file.exists(). Assert "error" in json.loads(failed_file.read_text()). Assert result is None. Assert not (perf_dir / f"review_{TODAY}.json").exists().

    test_terminal_summary: Patch stream with mock_stream_success. Patch PERF_DIR and DB_PATH. Call run(). Use capsys.readouterr(). Assert "Verdict:" in captured.out OR "PROFITABLE" in captured.out. Separately test failure path: patch stream with mock_stream_exception, call run(), assert "Review generation failed" in capsys.readouterr().out.
  </action>
  <verify>
    <automated>cd C:/Users/katuk/OneDrive/Desktop/projects/stockss && python -m pytest tests/test_agent_i9.py --collect-only -q 2>&1 | head -30</automated>
  </verify>
  <done>tests/test_agent_i9.py contains exactly 10 test functions. `pytest tests/test_agent_i9.py --collect-only` shows 10 test IDs without collection errors (ImportError from missing agent_i9.py is expected at run time, not collection time — if ImportError appears at collection, wrap the import in a try/except at module level with a pytest.skip or use importlib). All 10 tests FAIL when run (RED state confirmed).</done>
  <acceptance_criteria>
    - `python -m pytest tests/test_agent_i9.py --collect-only -q` lists 10 test function names
    - The 10 test IDs match: test_prompt_construction, test_token_cap_truncation, test_parse_valid_response, test_partial_response_saved, test_reject_max_positions, test_reject_min_rr, test_reject_risk_pct, test_output_file_success, test_output_file_failure, test_terminal_summary
    - `python -m pytest tests/test_agent_i9.py -x -q` exits non-zero (tests fail — RED state)
    - tests/test_agent_i9.py contains "from agents.agent_i9 import AgentI9, DailyReview, ParameterChange"
    - tests/test_agent_i9.py contains "test_reject_risk_pct" and "suggested_value=2.0" (percentage-form threshold per D-07)
    - tests/test_agent_i9.py contains "1.0%" (RISK_PER_TRADE_PCT displayed as percentage per planning constraint)
  </acceptance_criteria>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| test → agent_i9 import | Tests import the not-yet-existing module; ImportError at collection is a failure signal |
| fixture → SQLite | in_memory_db creates real SQLite file in tmp_path; no production DB touched |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04C-SC | Tampering | npm/pip/cargo installs | accept | No new packages in Phase 4C; all deps verified installed (anthropic 0.86.0, pydantic 2.12.5, tabulate 0.10.0) |
| T-04C-01 | Information Disclosure | conftest.py fixtures | accept | Test fixtures use hardcoded dummy values; no real API keys or production data in test files |
</threat_model>

<verification>
After both tasks complete:

```bash
cd C:/Users/katuk/OneDrive/Desktop/projects/stockss && python -m pytest tests/test_agent_i9.py -x -q
```

Expected: 10 tests collected, all FAIL with ImportError or AttributeError (agents/agent_i9.py not yet created). This is the correct RED state confirming tests are meaningful.
</verification>

<success_criteria>
- tests/__init__.py exists (empty)
- tests/conftest.py has 6 fixtures and no import errors
- tests/test_agent_i9.py has 10 test functions covering AGNT-13 through AGNT-16
- All 10 tests FAIL before agent_i9.py exists (RED confirmed)
- No production code files created or modified in this plan
</success_criteria>

<output>
Create `.planning/phases/04C-post-market-agent/04C-01-SUMMARY.md` when done
</output>
