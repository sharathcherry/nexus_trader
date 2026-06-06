---
phase: 04C
plan: 02
type: execute
wave: 2
depends_on:
  - 04C-01
files_modified:
  - agents/agent_i9.py
autonomous: true
requirements:
  - AGNT-13
  - AGNT-14
  - AGNT-15
  - AGNT-16

must_haves:
  truths:
    - "AgentI9(portfolio).run() returns a DailyReview instance when Claude Sonnet responds with valid JSON"
    - "run() returns None and writes review_failed_YYYYMMDD.json when any Anthropic exception is raised"
    - "Prompt never exceeds 10,000 estimated tokens — truncation warnings are logged when reduction was applied"
    - "RISK_PER_TRADE_PCT is embedded in the system prompt as '1.0%' (percentage form), not 0.01 (decimal)"
    - "Any parameter suggestion that raises MAX_OPEN_POSITIONS, lowers MIN_RISK_REWARD below 1.5, or raises RISK_PER_TRADE_PCT above 1.5% is removed from parameter_adjustments with a WARNING log"
    - "review_YYYYMMDD.json is written on success; review_partial + review_failed on bad JSON; review_failed only on stream exception"
    - "Tabulate trade summary prints to terminal in all three output states"
    - "pytest tests/test_agent_i9.py -x -q passes (all 10 tests GREEN)"
  artifacts:
    - path: "agents/agent_i9.py"
      provides: "AgentI9 class, DailyReview schema, ParameterChange schema, all private helpers"
      exports:
        - AgentI9
        - DailyReview
        - ParameterChange
    - path: "logs/performance/"
      provides: "Output directory (created at AgentI9.__init__ time)"
  key_links:
    - from: "agents/agent_i9.py"
      to: "execution/portfolio.db"
      via: "_get_rolling_stats() sqlite3.connect(DB_PATH)"
      pattern: "sqlite3.connect.*DB_PATH"
    - from: "agents/agent_i9.py"
      to: "Anthropic API"
      via: "self._client.messages.stream(model=MODEL, ...)"
      pattern: "client.messages.stream"
    - from: "agents/agent_i9.py"
      to: "logs/performance/"
      via: "Path.write_text() for review JSON files"
      pattern: "perf_dir.*write_text"
---

<objective>
Implement agents/agent_i9.py — the complete AgentI9 class — and make all 10 tests from Plan 01 GREEN.

Purpose: Delivers the post-market Claude Sonnet reviewer that reads today's closed trades and 20-day rolling stats, calls Claude with streaming, parses the structured response, enforces three parameter-safety rules, and saves the result to logs/performance/ with a tabulate terminal summary.
Output: agents/agent_i9.py fully implementing AGNT-13 through AGNT-16.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/phases/04C-post-market-agent/04C-CONTEXT.md
@.planning/phases/04C-post-market-agent/04C-RESEARCH.md
@.planning/phases/04C-post-market-agent/04C-PATTERNS.md
@.planning/phases/04C-post-market-agent/04C-01-SUMMARY.md

<interfaces>
<!-- Contracts this plan must satisfy. Verified from source files. -->

From config.py (lines 1–57):
```python
config.ANTHROPIC_API_KEY   # str — API key
config.MAX_OPEN_POSITIONS  # int = 5
config.MIN_RISK_REWARD     # float = 1.5
config.RISK_PER_TRADE_PCT  # float = 0.01 (DECIMAL — multiply by 100 before embedding in prompt)
```

From utils/logger.py (lines 1–54):
```python
setup_logger(name: str) -> logging.Logger
# Module-level usage: logger = setup_logger(__name__)
```

From execution/portfolio.py — assumed interface (A1 in RESEARCH.md):
```python
class PaperPortfolio:
    def get_daily_report(self) -> list[dict]:
        # Returns list of closed trade dicts with keys:
        # symbol, strategy, entry_price, exit_price, qty,
        # gross_pnl, brokerage, net_pnl, exit_reason, entry_time, exit_time
```

trades table schema (Phase 3 CONTEXT.md D-01):
columns: id, symbol, entry_price, exit_price, qty, strategy, entry_time, exit_time, gross_pnl, brokerage, net_pnl, exit_reason

Anthropic SDK 0.86.0 streaming (from RESEARCH.md Pattern 1):
```python
with client.messages.stream(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": prompt_text}],
) as stream:
    for text in stream.text_stream:
        full_text += text
    final_msg = stream.get_final_message()   # MUST be inside with block
    tokens_used = final_msg.usage.input_tokens + final_msg.usage.output_tokens
```

Exception types to catch (anthropic 0.86.0):
anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError, anthropic.APIStatusError
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement agents/agent_i9.py (GREEN — make all 10 tests pass)</name>
  <files>agents/agent_i9.py</files>
  <read_first>
    - tests/test_agent_i9.py (every assertion in every test — this is the spec)
    - tests/conftest.py (fixture structure, especially mock_stream_success JSON shape and in_memory_db schema)
    - .planning/phases/04C-post-market-agent/04C-PATTERNS.md (all 8 patterns — full code examples)
    - .planning/phases/04C-post-market-agent/04C-RESEARCH.md (Pattern 1 streaming, Pattern 2 Pydantic, Pattern 3 SQLite, Pattern 4 three-state, Pattern 5 param validation, Pattern 6 token cap; Pitfalls 1-5)
    - .planning/phases/04C-post-market-agent/04C-CONTEXT.md (D-01 through D-11 locked decisions)
    - config.py (attribute names — must match exactly)
    - utils/logger.py (setup_logger signature)
  </read_first>
  <behavior>
    Module-level constants:
    - PERF_DIR = Path("logs/performance")
    - DB_PATH = Path("execution/portfolio.db")
    - MODEL = "claude-sonnet-4-6"
    - MAX_TOKENS = 2048
    - TOKEN_CAP = 10_000
    - CHARS_PER_TOKEN = 4
    - SYSTEM_PROMPT = (analytical, concise, NSE-specific tone; instructs Claude to respond with a single JSON object matching DailyReview schema; mentions data is 15-min delayed per STATE.md decision)

    Pydantic models at module level (not nested in class):
    - ParameterChange(BaseModel): param_name str, current_value float, suggested_value float, reason str
    - DailyReview(BaseModel): session_verdict str, winning_strategies list[str], underperforming_strategies list[str], parameter_adjustments list[ParameterChange], tomorrow_watch list[str], summary str

    AgentI9.__init__(self, portfolio: PaperPortfolio):
    - self.portfolio = portfolio
    - self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    - PERF_DIR.mkdir(parents=True, exist_ok=True)

    AgentI9._estimate_tokens(self, text: str) -> int:
    - return len(text) // CHARS_PER_TOKEN

    AgentI9._get_rolling_stats(self, days: int = 20) -> dict:
    - Open sqlite3.connect(DB_PATH), conn.row_factory = sqlite3.Row
    - try/finally: conn.close()
    - Query strategy_rows: SELECT strategy, COUNT(*) AS trade_count, AVG(net_pnl) AS avg_net_pnl, SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate FROM trades WHERE DATE(exit_time) >= DATE('now', :days) GROUP BY strategy, with param {"days": f"-{days} days"}
    - Query totals: SELECT COUNT(*) AS total_trades, SUM(net_pnl) AS total_net_pnl, SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate_overall FROM trades WHERE DATE(exit_time) >= DATE('now', :days), same param
    - Return dict with "strategy_breakdown" (list of dicts) and "totals" (dict, handle None result)
    - On sqlite3.OperationalError: logger.error(), return {"strategy_breakdown": [], "totals": {}}

    AgentI9._build_prompt(self, today_trades: list[dict], rolling_stats: dict, omit_times: bool = False) -> str:
    - Build a multi-section text prompt:
      Section 1 "CURRENT CONFIG": embed config.MAX_OPEN_POSITIONS, config.MIN_RISK_REWARD, and config.RISK_PER_TRADE_PCT * 100 formatted as "1.0%" — NEVER embed the raw 0.01 decimal
      Section 2 "TODAY'S TRADES": tabulate today_trades rows; if omit_times=True, omit entry_time and exit_time columns
      Section 3 "20-DAY ROLLING STATS": strategy_breakdown table + totals; omit avg_rr_achieved (trades table lacks stop_loss — per planning constraint)
      Section 4 "DATA NOTE": "Note: yfinance NSE data is 15-minute delayed. All prices reflect ~15min lag from live market."
    - Return the combined prompt string

    AgentI9._validate_parameter_adjustments(self, adjustments: list[ParameterChange]) -> list[ParameterChange]:
    - Iterate adjustments; apply three rejection rules per D-07:
      1. param_name == "MAX_OPEN_POSITIONS" AND suggested_value > config.MAX_OPEN_POSITIONS → reject + WARNING
      2. param_name == "MIN_RISK_REWARD" AND suggested_value < 1.5 → reject + WARNING
      3. param_name == "RISK_PER_TRADE_PCT" AND suggested_value > 1.5 → reject + WARNING (threshold 1.5 = 1.5%, assumes prompt used percentage form)
    - Return list of non-rejected items

    AgentI9._print_summary(self, review: DailyReview | None, state: str, today_str: str, today_trades: list[dict]) -> None:
    - state == "success": tabulate(rows, headers=["Symbol","Strategy","Entry","Exit","Net P&L","Reason"], tablefmt="grid", floatfmt=".2f") then print f"\nVerdict: {review.session_verdict}" and f"Summary: {review.summary}"
    - state == "partial": print f"Partial review — raw text saved to review_partial_{today_str}.json"
    - else ("failed"): print f"Review generation failed — check review_failed_{today_str}.json"

    AgentI9.run(self) -> DailyReview | None:
    - today_str = date.today().strftime("%Y%m%d")
    - _review_state = "failed" (default)
    - _failure_detail = ""
    - review: DailyReview | None = None
    - full_text = ""

    Step 1 — Get today's trades:
      today_trades = self.portfolio.get_daily_report() or []

    Step 2 — Get rolling stats (handle missing DB gracefully):
      rolling_stats = self._get_rolling_stats(days=20)

    Step 3 — Build prompt with progressive token cap reduction:
      prompt_text = self._build_prompt(today_trades, rolling_stats)
      for days in [20, 15, 10]:
        if self._estimate_tokens(prompt_text) <= TOKEN_CAP: break
        rolling_stats = self._get_rolling_stats(days=days)
        prompt_text = self._build_prompt(today_trades, rolling_stats)
        logger.warning(f"Prompt truncated to {days}-day window to stay under token cap")
      if self._estimate_tokens(prompt_text) > TOKEN_CAP:
        prompt_text = self._build_prompt(today_trades, rolling_stats, omit_times=True)
        logger.warning("Dropped entry_time/exit_time fields to stay under token cap")
      logger.info(f"Prompt estimated tokens: {self._estimate_tokens(prompt_text)}")

    Step 4 — Stream call (inside try/except block for Anthropic exceptions):
      full_text = ""
      tokens_used = 0
      try:
        with self._client.messages.stream(...) as stream:
          for text in stream.text_stream: full_text += text
          final_msg = stream.get_final_message()  # INSIDE with block
          tokens_used = final_msg.usage.input_tokens + final_msg.usage.output_tokens
        logger.info(f"Claude stream complete — {tokens_used} tokens used")
      except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
        logger.error(f"Claude API error: {e}")
        _review_state = "failed"
        _failure_detail = str(e)

    Step 5 — Parse JSON and validate (only if stream succeeded, i.e., no exception path):
      if _review_state != "failed":
        try:
          data = json.loads(full_text)
          review = DailyReview(**data)
          review.parameter_adjustments = self._validate_parameter_adjustments(review.parameter_adjustments)
          _review_state = "success"
        except json.JSONDecodeError as e:
          logger.error(f"JSON parse failed: {e}")
          _review_state = "partial"
        except ValidationError as e:
          logger.error(f"Schema validation failed: {e}")
          _review_state = "partial"

    Step 6 — Single-exit file write block (prevents Pitfall 5 overwrite):
      if _review_state == "success":
        (PERF_DIR / f"review_{today_str}.json").write_text(review.model_dump_json(indent=2), encoding="utf-8")
      elif _review_state == "partial":
        (PERF_DIR / f"review_partial_{today_str}.json").write_text(full_text, encoding="utf-8")
        (PERF_DIR / f"review_failed_{today_str}.json").write_text(json.dumps({"error": "json_parse_failed", "date": today_str}), encoding="utf-8")
      else:  # "failed"
        (PERF_DIR / f"review_failed_{today_str}.json").write_text(json.dumps({"error": "stream_exception", "date": today_str, "detail": _failure_detail}), encoding="utf-8")

    Step 7 — Print tabulate summary (all three states):
      self._print_summary(review, _review_state, today_str, today_trades)

    Step 8 — Return:
      return review if _review_state == "success" else None
  </behavior>
  <action>
    Create agents/agent_i9.py. Begin with standard imports block per PATTERNS.md imports pattern:
    from __future__ import annotations, then stdlib imports (json, sqlite3, datetime.date, pathlib.Path, typing.TYPE_CHECKING), then third-party (anthropic, pydantic.BaseModel, pydantic.ValidationError, tabulate.tabulate), then local (from config import config, from utils.logger import setup_logger). TYPE_CHECKING guard for PaperPortfolio import.

    Module-level: logger = setup_logger(__name__) and the 6 constants (PERF_DIR, DB_PATH, MODEL, MAX_TOKENS, TOKEN_CAP, CHARS_PER_TOKEN).

    SYSTEM_PROMPT constant (multi-line string): tone is analytical and concise; instructs Claude it is reviewing an NSE India intraday paper trading session; asks for a single JSON object with exactly the DailyReview schema keys (list them explicitly); includes the note that data is 15-minute delayed; instructs session_verdict must be exactly "PROFITABLE", "BREAKEVEN", or "LOSS"; instructs parameter_adjustments current_value for RISK_PER_TRADE_PCT is expressed in percentage form (e.g., 1.0 means 1.0%); instructs tomorrow_watch contains up to 5 NSE symbol strings only.

    Define ParameterChange(BaseModel) and DailyReview(BaseModel) at module level with the exact fields from D-06.

    Implement AgentI9 class with __init__, and all private methods in the order: _estimate_tokens, _get_rolling_stats, _build_prompt, _validate_parameter_adjustments, _print_summary, then the public run() method last.

    For _build_prompt: format RISK_PER_TRADE_PCT as f"{config.RISK_PER_TRADE_PCT * 100:.1f}%" (produces "1.0%"). Do NOT embed config.RISK_PER_TRADE_PCT raw (0.01). This is the single most critical implementation constraint.

    For the stream exception handling: use a single except clause catching a tuple of all 4 exception types. Do NOT use bare except or except Exception.

    For the state machine: initialize _review_state = "failed" before the streaming block. Only set to "success" after both JSON parse AND Pydantic validation succeed. Set to "partial" on JSONDecodeError or ValidationError. Keep "failed" for stream exceptions.

    For tabulate in _build_prompt: if today_trades is empty, emit "No trades today." as the section body instead of an empty table. Handle None totals from _get_rolling_stats gracefully (None total_trades → display 0).
  </action>
  <verify>
    <automated>cd C:/Users/katuk/OneDrive/Desktop/projects/stockss && python -m pytest tests/test_agent_i9.py -x -q 2>&1</automated>
  </verify>
  <done>All 10 tests pass (GREEN). agents/agent_i9.py is importable. `from agents.agent_i9 import AgentI9, DailyReview, ParameterChange` succeeds without error.</done>
  <acceptance_criteria>
    - `python -m pytest tests/test_agent_i9.py -x -q` exits 0 (all 10 tests pass)
    - `python -c "from agents.agent_i9 import AgentI9, DailyReview, ParameterChange; print('OK')"` prints OK
    - agents/agent_i9.py contains the string "claude-sonnet-4-6" (MODEL constant)
    - agents/agent_i9.py contains "RISK_PER_TRADE_PCT * 100" (percentage-form conversion in _build_prompt per planning constraint)
    - agents/agent_i9.py does NOT contain the literal string "RISK_PER_TRADE_PCT = 0.01" or embed "0.01" in the prompt — the raw decimal must never appear in prompt text
    - agents/agent_i9.py contains "get_final_message()" inside a "with" block (not after) — per planning constraint and RESEARCH.md Pitfall 1
    - agents/agent_i9.py contains "_review_state" variable (single-exit file-write pattern per planning constraint)
    - agents/agent_i9.py does NOT contain "avg_rr_achieved" — per planning constraint (trades table lacks stop_loss)
    - agents/agent_i9.py contains "15-min" or "15-minute" (yfinance data delay disclosed in prompt per STATE.md decision)
    - `python -m pytest tests/ -x -q` exits 0 (full test suite still green)
  </acceptance_criteria>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| AgentI9 → Anthropic API | Outbound HTTPS; API key from config (loaded from .env); key never logged |
| Claude response → DailyReview | Untrusted external response; parsed through Pydantic before any use |
| Pydantic DailyReview → parameter_adjustments | Validated struct, but values need safety-rule filtering (D-07) before any config use |
| AgentI9 → execution/portfolio.db | Read-only query; no writes to DB |
| AgentI9 → logs/performance/ | Write-only output; filename derived from date.today() (no user input in path) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04C-01 | Tampering | Claude response → parameter_adjustments | mitigate | D-07 three-rule auto-reject in _validate_parameter_adjustments before any downstream use; rejected items logged at WARNING |
| T-04C-02 | Tampering | Prompt injection via today_trades data | mitigate | System prompt instructs JSON-only response; all output goes through Pydantic DailyReview validation before use |
| T-04C-03 | Information Disclosure | ANTHROPIC_API_KEY | mitigate | Key read from config (which reads from .env); never logged or embedded in prompt; .env excluded from git (SCAF-05) |
| T-04C-04 | Tampering | Path traversal in output filenames | accept | Filename is date.today().strftime("%Y%m%d") — deterministic date string, zero user input; no traversal possible |
| T-04C-05 | Denial of Service | Prompt exceeds 10,000 token cap | mitigate | Progressive truncation in run() before API call: 20d → 15d → 10d window → drop time fields; logged at WARNING |
| T-04C-SC | Tampering | npm/pip/cargo installs | accept | No new packages; all deps pre-installed (anthropic 0.86.0, pydantic 2.12.5, tabulate 0.10.0) — no package manager invocations in this phase |
</threat_model>

<verification>
Full phase gate after Plan 02 completes:

```bash
cd C:/Users/katuk/OneDrive/Desktop/projects/stockss && python -m pytest tests/ -x -q
```

Expected: all 10 tests GREEN, exit 0.

Import smoke test:
```bash
python -c "from agents.agent_i9 import AgentI9, DailyReview, ParameterChange; print('imports OK')"
```

Critical invariant checks:
```bash
python -c "
import agents.agent_i9 as m
import inspect
src = inspect.getsource(m)
assert 'RISK_PER_TRADE_PCT * 100' in src, 'RISK_PCT must be percentage form in prompt'
assert 'avg_rr_achieved' not in src, 'avg_rr_achieved must be omitted (no stop_loss column)'
assert '15-min' in src or '15-minute' in src, 'data delay note required in prompt'
assert '_review_state' in src, 'single-exit state machine required'
print('invariants OK')
"
```
</verification>

<success_criteria>
- agents/agent_i9.py exists and is importable
- AgentI9 class exports: __init__(portfolio), run() -> DailyReview | None, plus private helpers
- DailyReview and ParameterChange Pydantic models exported from module
- All 10 tests in tests/test_agent_i9.py pass
- RISK_PER_TRADE_PCT embedded in prompt as percentage form (1.0%), not raw decimal
- avg_rr_achieved absent from rolling stats (trades table lacks stop_loss column)
- Three output states implemented with single-exit file-write block
- Tabulate summary prints in all three output states
- AGNT-13, AGNT-14, AGNT-15, AGNT-16 all satisfied
</success_criteria>

<output>
Create `.planning/phases/04C-post-market-agent/04C-02-SUMMARY.md` when done
</output>
