# Phase 4C: Post-Market Agent - Research

**Researched:** 2026-06-06
**Domain:** Anthropic SDK streaming, SQLite querying, Pydantic v2 validation, Python file I/O
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Stream with `client.messages.stream()`, accumulate `full_text` via `stream.text_stream`, call `json.loads(full_text)` + Pydantic validation after stream completes. Get usage from `stream.get_final_message()` INSIDE the `with` block after `text_stream` is exhausted.
- **D-02:** Model `claude-sonnet-4-6`, prompt cap 10,000 tokens, log token count at INFO using `final_msg.usage.input_tokens + final_msg.usage.output_tokens`.
- **D-03:** System prompt instructs plain JSON response matching `DailyReview` schema. No tool_use, no function calling.
- **D-04:** Three output states — full valid (`review_YYYYMMDD.json`), stream completes but JSON invalid (`review_partial_YYYYMMDD.json` + `review_failed_YYYYMMDD.json`), stream raises exception (`review_failed_YYYYMMDD.json` only).
- **D-05:** Tabulate terminal summary prints in ALL three states.
- **D-06:** `DailyReview` Pydantic model with `ParameterChange` sub-model (full schema defined below).
- **D-07:** Parameter advisory auto-reject 3 rule violations (MAX_OPEN_POSITIONS raised, MIN_RISK_REWARD lowered below 1.5, RISK_PER_TRADE_PCT raised above 1.5%).
- **D-08:** `tomorrow_watch` is `list[str]` symbols only. No sector tags. No extra validation beyond D-07 rules.
- **D-09:** 20-day rolling stats from SQLite `trades` table, strategy-level breakdown + overall totals.
- **D-10:** Token cap truncation — drop oldest days first, then drop `entry_time`/`exit_time` fields.
- **D-11:** Output files in `logs/performance/` — `review_YYYYMMDD.json` / `review_partial_YYYYMMDD.json` / `review_failed_YYYYMMDD.json`.

### Claude's Discretion

- Exact system prompt wording (tone: analytical, concise, NSE-specific)
- Whether to include VWAP/ATR values in the per-trade ledger sent to Claude
- Exact tabulate table columns for terminal summary (suggested: symbol, strategy, entry, exit, net_pnl, exit_reason)
- Whether `session_verdict` is inferred by AgentI9 from `net_pnl` or trusted from Claude's response

### Deferred Ideas (OUT OF SCOPE)

- Telegram notification with review summary (ALRT-01/v2 scope)
- Auto-apply validated parameter suggestions to config (explicitly out-of-scope in REQUIREMENTS.md)
- Multi-day trend analysis (Sharpe, max drawdown) in the Claude prompt — deferred to v2
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AGNT-13 | AgentI9 calls Claude Sonnet at 3:30 PM with full daily trade ledger and 20-day rolling stats; prompt capped at 10,000 tokens; streaming used | Streaming pattern verified in SDK 0.86.0; token estimation via `len(text)//4`; SQLite rolling stats query verified |
| AGNT-14 | AgentI9 parses Claude response: session_verdict, winning/underperforming strategies, parameter_adjustments, tomorrow_watch | Pydantic v2 `BaseModel` + `ValidationError` pattern verified; `json.loads()` + `DailyReview(**data)` pattern confirmed |
| AGNT-15 | AgentI9 auto-rejects any Claude suggestion that raises MAX_OPEN_POSITIONS, lowers MIN_RISK_REWARD below 1.5, or raises RISK_PER_TRADE_PCT above 1.5% | Config attributes verified: `config.MAX_OPEN_POSITIONS=5`, `config.MIN_RISK_REWARD=1.5`; RISK_PCT representation issue flagged (see Pitfall 3) |
| AGNT-16 | AgentI9 saves review JSON to logs/performance/; on API failure writes sentinel; formatted tabulate summary prints in all cases | `Path.mkdir(parents=True, exist_ok=True)` pattern verified; tabulate 0.10.0 confirmed; all three file naming patterns confirmed |
</phase_requirements>

---

## Summary

Phase 4C delivers `agents/agent_i9.py` — a class that runs once post-market, builds a structured prompt from today's closed trades and 20-day rolling SQLite stats, calls Claude Sonnet via streaming, parses the JSON response into a Pydantic `DailyReview` model, validates parameter suggestions against three safety rules, and saves the result with appropriate fallback files.

All five key technologies are available and verified on the target machine: `anthropic 0.86.0`, `pydantic 2.12.5`, `tabulate 0.10.0`, `sqlite3` (stdlib), and `pathlib` (stdlib). No new package installs are required. The `execution/portfolio.db` SQLite file and its `trades` table (created in Phase 3) is the sole external dependency at runtime.

The most critical implementation subtlety is the Anthropic streaming pattern: `get_final_message()` must be called INSIDE the `with client.messages.stream(...) as stream:` block, after `text_stream` is exhausted, to safely access `usage.input_tokens` and `usage.output_tokens`. Calling it after the `with` block exits still works (the `__final_message_snapshot` is already set) but the raw HTTP connection has been released.

One schema gap was identified: `avg_rr_achieved` mentioned in D-09 is not computable from the `trades` table schema (which lacks `stop_loss`). The planner must decide whether to omit this field or add `stop_loss` to the `trades` schema. Both options are documented in Open Questions.

**Primary recommendation:** Implement AgentI9 as a single class with `__init__(self, portfolio: PaperPortfolio)` and `async def run() -> dict | None`. Use `get_final_text()` inside the `with` block as the simplest accumulation strategy (it calls `get_final_message()` internally), then parse outside the block.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Trade ledger assembly | API / Backend (AgentI9) | — | PaperPortfolio.get_daily_report() owns closed trade data |
| 20-day rolling stats | API / Backend (AgentI9) | Database / Storage (SQLite) | AgentI9 queries trades table directly — not via PaperPortfolio method |
| Prompt construction + token cap | API / Backend (AgentI9) | — | AgentI9 owns truncation logic |
| Claude Sonnet API call | API / Backend (AgentI9) | External (Anthropic API) | Streaming HTTP call |
| JSON parsing + Pydantic validation | API / Backend (AgentI9) | — | Local parse after stream completes |
| Parameter advisory validation | API / Backend (AgentI9) | — | Rule-check against config constants |
| File persistence | API / Backend (AgentI9) | Database / Storage (logs/performance/) | Path.write_text() pattern |
| Terminal output | Browser / Client (terminal) | — | tabulate prints to stdout |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `anthropic` | 0.86.0 (installed) | Claude Sonnet streaming client | Project SDK; streaming confirmed via `MessageStream` class |
| `pydantic` | 2.12.5 (installed) | DailyReview schema validation | Transitive dep of anthropic; BaseModel, ValidationError verified |
| `sqlite3` | stdlib | Direct DB query for 20-day stats | Already used by PaperPortfolio in Phase 3 |
| `tabulate` | 0.10.0 (installed) | Terminal trade summary table | Already in requirements.txt |
| `pathlib.Path` | stdlib | logs/performance/ directory + file writes | Standard project pattern |

[VERIFIED: installed packages confirmed via `pip show`]

### No New Packages Required

Phase 4C requires zero new installs. All dependencies are already in `requirements.txt` or Python stdlib.

---

## Package Legitimacy Audit

No new packages are introduced in this phase. All packages used (`anthropic`, `pydantic`, `tabulate`) were added in prior phases and are already in `requirements.txt`. Slopcheck not run — no new packages to evaluate.

---

## Architecture Patterns

### System Architecture Diagram

```
PaperPortfolio.get_daily_report()
        |
        v
AgentI9.run()
  |-- Build prompt
  |     |-- Today's trades (from portfolio method)
  |     |-- 20-day rolling stats (direct SQLite query on trades table)
  |     |-- Config params block
  |     |-- Token cap check (len(prompt)//4 > 10000?)
  |           YES: drop oldest days -> retry cap check
  |                 still over? drop entry_time/exit_time fields -> log WARNING
  |
  |-- Log estimated token count at INFO
  |
  |-- with client.messages.stream(...) as stream:
  |     for text in stream.text_stream: full_text += text
  |     get final_msg (for usage) INSIDE with block
  |     [EXCEPTION path] -> write review_failed_YYYYMMDD.json -> tabulate summary -> return
  |
  |-- json.loads(full_text)
  |     [JSONDecodeError path] -> write review_partial + review_failed -> tabulate summary -> return
  |
  |-- DailyReview(**data)
  |     [ValidationError path] -> write review_partial + review_failed -> tabulate summary -> return
  |
  |-- Validate parameter_adjustments (3 safety rules)
  |     remove rejected items, log WARNING per rejection
  |
  |-- Write review_YYYYMMDD.json (model_dump_json)
  |-- Print tabulate summary to terminal
  |-- Return DailyReview object
```

### Recommended Project Structure

```
agents/
├── __init__.py          # exists (empty)
├── agent_i9.py          # THIS phase — AgentI9 class
execution/
├── __init__.py          # exists (empty)
├── portfolio.py         # Phase 3 — PaperPortfolio (get_daily_report)
├── portfolio.db         # runtime — SQLite (trades table)
logs/
├── performance/         # created by AgentI9 on first run if absent
│   ├── review_YYYYMMDD.json        # success
│   ├── review_partial_YYYYMMDD.json # partial stream
│   └── review_failed_YYYYMMDD.json  # failure sentinel
```

### Pattern 1: Anthropic Streaming with Usage Capture

**What:** Stream text chunks, accumulate full text, capture usage stats — all inside one `with` block.

**When to use:** Any time you need the complete text plus token counts from a streaming call.

```python
# Source: anthropic 0.86.0 SDK — MessageStream, MessageStreamManager verified
import anthropic

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
full_text = ""
tokens_used = 0

try:
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt_text}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
        # get_final_message() safe inside with block after text_stream exhausted
        final_msg = stream.get_final_message()
        tokens_used = final_msg.usage.input_tokens + final_msg.usage.output_tokens

    logger.info(f"Claude stream complete — {tokens_used} tokens used")

except anthropic.APIConnectionError as e:
    logger.error(f"Connection error: {e}")
    # write review_failed_YYYYMMDD.json
except anthropic.APITimeoutError as e:
    logger.error(f"Timeout: {e}")
    # write review_failed_YYYYMMDD.json
except anthropic.RateLimitError as e:
    logger.error(f"Rate limit hit: {e}")
    # write review_failed_YYYYMMDD.json
except anthropic.APIStatusError as e:
    logger.error(f"API error {e.status_code}: {e.message}")
    # write review_failed_YYYYMMDD.json
```

[VERIFIED: anthropic 0.86.0 installed; `MessageStream.text_stream`, `get_final_message()`, `usage.input_tokens`, `usage.output_tokens` confirmed via source inspection]

### Pattern 2: Pydantic v2 Parse + ValidationError Catch

**What:** Parse a JSON dict into a validated Pydantic model, catch schema violations.

```python
# Source: pydantic 2.12.5 installed — BaseModel, ValidationError verified
from pydantic import BaseModel, ValidationError
import json

class ParameterChange(BaseModel):
    param_name: str
    current_value: float
    suggested_value: float
    reason: str

class DailyReview(BaseModel):
    session_verdict: str
    winning_strategies: list[str]
    underperforming_strategies: list[str]
    parameter_adjustments: list[ParameterChange]
    tomorrow_watch: list[str]
    summary: str

# Parse path (after stream completes)
try:
    data = json.loads(full_text)
    review = DailyReview(**data)
except json.JSONDecodeError as e:
    logger.error(f"JSON parse failed: {e}")
    # write review_partial + review_failed, return
except ValidationError as e:
    logger.error(f"Schema validation failed: {e}")
    # write review_partial + review_failed, return

# Serialize to file
Path(output_path).write_text(review.model_dump_json(indent=2), encoding="utf-8")
```

[VERIFIED: pydantic 2.12.5; `BaseModel`, `ValidationError`, `model_dump_json()` confirmed via live test]

### Pattern 3: Direct SQLite Query for Rolling Stats

**What:** Open `execution/portfolio.db` directly (not via PaperPortfolio) to compute 20-day strategy stats.

```python
# Source: sqlite3 stdlib — column names from Phase 3 CONTEXT.md D-01
import sqlite3
from pathlib import Path

DB_PATH = Path("execution/portfolio.db")

def _get_rolling_stats(days: int = 20) -> dict:
    """Returns strategy breakdown + overall totals for last N trading days."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        strategy_rows = conn.execute("""
            SELECT strategy,
                   COUNT(*)                                            AS trade_count,
                   AVG(net_pnl)                                        AS avg_net_pnl,
                   SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0
                       / COUNT(*)                                      AS win_rate
            FROM trades
            WHERE DATE(exit_time) >= DATE('now', :days)
            GROUP BY strategy
        """, {"days": f"-{days} days"}).fetchall()

        totals = conn.execute("""
            SELECT COUNT(*)                                            AS total_trades,
                   SUM(net_pnl)                                        AS total_net_pnl,
                   SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0
                       / COUNT(*)                                      AS win_rate_overall
            FROM trades
            WHERE DATE(exit_time) >= DATE('now', :days)
        """, {"days": f"-{days} days"}).fetchone()

        return {
            "strategy_breakdown": [dict(r) for r in strategy_rows],
            "totals": dict(totals) if totals else {}
        }
    finally:
        conn.close()
```

[VERIFIED: sqlite3 stdlib; column names (symbol, entry_price, exit_price, qty, strategy, entry_time, exit_time, gross_pnl, brokerage, net_pnl, exit_reason) confirmed from Phase 3 CONTEXT.md D-01; query verified live against in-memory DB]

### Pattern 4: Three-State Output with File Persistence

**What:** Write different files depending on how much the stream produced.

```python
# Source: pathlib stdlib — verified filename patterns
from pathlib import Path
from datetime import date
import json

today_str = date.today().strftime("%Y%m%d")
perf_dir = Path("logs/performance")
perf_dir.mkdir(parents=True, exist_ok=True)

# Success path
(perf_dir / f"review_{today_str}.json").write_text(
    review.model_dump_json(indent=2), encoding="utf-8"
)

# Partial path (JSON parse/validation failed but text was received)
(perf_dir / f"review_partial_{today_str}.json").write_text(
    full_text, encoding="utf-8"
)
(perf_dir / f"review_failed_{today_str}.json").write_text(
    json.dumps({"error": "json_parse_failed", "date": today_str}),
    encoding="utf-8",
)

# Full failure path (exception during stream)
(perf_dir / f"review_failed_{today_str}.json").write_text(
    json.dumps({"error": "stream_exception", "date": today_str, "detail": str(e)}),
    encoding="utf-8",
)
```

[VERIFIED: pathlib stdlib; date format `%Y%m%d` confirmed produces e.g. `20260606`]

### Pattern 5: Parameter Advisory Validation

**What:** Filter `parameter_adjustments` list per D-07 safety rules.

```python
# Source: config.py verified attributes
from config import config

def _validate_parameter_adjustments(
    adjustments: list[ParameterChange],
) -> list[ParameterChange]:
    """Remove unsafe parameter suggestions. Returns cleaned list."""
    valid = []
    for adj in adjustments:
        rejected = False
        if (adj.param_name == "MAX_OPEN_POSITIONS"
                and adj.suggested_value > config.MAX_OPEN_POSITIONS):
            logger.warning(
                f"Auto-rejected: {adj.param_name} suggestion {adj.suggested_value} "
                f"exceeds limit {config.MAX_OPEN_POSITIONS}"
            )
            rejected = True
        elif (adj.param_name == "MIN_RISK_REWARD"
                and adj.suggested_value < 1.5):
            logger.warning(
                f"Auto-rejected: {adj.param_name} suggestion {adj.suggested_value} "
                f"weakens R:R floor (min 1.5)"
            )
            rejected = True
        elif (adj.param_name == "RISK_PER_TRADE_PCT"
                and adj.suggested_value > 1.5):
            # NOTE: threshold 1.5 assumes Claude returns percentage form (1.5 = 1.5%)
            # System prompt must present RISK_PER_TRADE_PCT as 1.0% not 0.01
            logger.warning(
                f"Auto-rejected: {adj.param_name} suggestion {adj.suggested_value}% "
                f"exceeds risk ceiling 1.5%"
            )
            rejected = True
        if not rejected:
            valid.append(adj)
    return valid
```

[VERIFIED: config.py attributes confirmed: `MAX_OPEN_POSITIONS=5`, `MIN_RISK_REWARD=1.5`, `RISK_PER_TRADE_PCT=0.01`]

### Pattern 6: Token Cap Truncation

**What:** Estimate prompt tokens and drop data until under 10,000 token cap.

```python
# Source: CONTEXT.md D-10 — 4 chars/token heuristic
TOKEN_CAP = 10_000
CHARS_PER_TOKEN = 4  # conservative heuristic

def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN

# Build prompt from full rolling window
prompt_text = _build_prompt(today_trades, rolling_stats_20d)

# If over cap, progressively reduce rolling window
for days in [20, 15, 10]:
    if _estimate_tokens(prompt_text) <= TOKEN_CAP:
        break
    rolling_stats = _get_rolling_stats(days=days)
    prompt_text = _build_prompt(today_trades, rolling_stats)
    logger.warning(f"Prompt truncated to {days}-day window to stay under token cap")

# If still over after 10-day window, drop time fields from today's trades
if _estimate_tokens(prompt_text) > TOKEN_CAP:
    prompt_text = _build_prompt(today_trades, rolling_stats, omit_times=True)
    logger.warning("Dropped entry_time/exit_time fields to stay under token cap")

logger.info(f"Prompt estimated tokens: {_estimate_tokens(prompt_text)}")
```

### Anti-Patterns to Avoid

- **Calling `get_final_message()` after the `with` block exits to get usage:** The HTTP connection is closed but the snapshot is technically still available. Still, call it INSIDE the `with` block for clarity and safety.
- **Using `stream.get_final_text()` and also iterating `stream.text_stream`:** These are alternative approaches, not additive. `get_final_text()` internally calls `get_final_message()` which calls `until_done()` — if you've already exhausted `text_stream`, calling `get_final_text()` afterward is safe but redundant. Pick one strategy.
- **Passing `RISK_PER_TRADE_PCT` decimal value (0.01) directly to Claude:** Claude will interpret 0.01 as a percentage and suggest values like 0.012, not 1.2. Always convert to percentage form (multiply by 100) before embedding in the prompt. The D-07 threshold of 1.5 only works if the prompt shows `1.0%` (percentage form).
- **Opening `portfolio.db` without `finally: conn.close()`:** SQLite connections leak if exceptions occur mid-query. Use `try/finally` or a context manager.
- **Building rolling stats from `PaperPortfolio.get_daily_report()`:** That method only returns TODAY's closed trades. 20-day history requires a direct SQLite query.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Response schema validation | Custom dict key checks | `pydantic.BaseModel` | Handles nested models, type coercion, clear error messages |
| JSON stream accumulation | Manual chunk buffer + partial JSON parser | `full_text += text` then `json.loads(full_text)` | Stream always delivers complete JSON when `end_turn` fires |
| File encoding issues | Binary write + manual encode | `Path.write_text(..., encoding="utf-8")` | Handles NSE symbol names with UTF chars if any |
| Token counting | tiktoken or tokenizer install | `len(text) // 4` heuristic | Sufficient for cap checking; avoids new dependency |

---

## Common Pitfalls

### Pitfall 1: `get_final_message()` Called After `with` Block — Usage Data Inaccessible

**What goes wrong:** Developer calls `stream.get_final_message()` outside the `with` block to get token usage. The HTTP stream is closed, but `__final_message_snapshot` is still set on the Python object, so it actually works. However, if an exception interrupted the stream mid-way, `__final_message_snapshot` may be `None`, causing `AssertionError`.

**Why it happens:** The `MessageStreamManager.__exit__` calls `stream.close()` which closes the raw HTTP connection — but it does NOT clear `__final_message_snapshot`. So post-`with` calls succeed on happy path but fail if stream was interrupted.

**How to avoid:** Always call `get_final_message()` INSIDE the `with` block, after `text_stream` is fully consumed. This is the documented pattern in the SDK.

**Warning signs:** `AssertionError: None` on the line `assert self.__final_message_snapshot is not None`.

### Pitfall 2: `avg_rr_achieved` Is Not Computable from `trades` Table Schema

**What goes wrong:** D-09 mentions `avg_rr_achieved` as a rolling stats field, but the `trades` table (Phase 3 schema) does not store `stop_loss`. R:R achieved = `(exit_price - entry_price) / (entry_price - stop_loss)` — the denominator is unavailable.

**Why it happens:** The `positions` table stores `stop_loss` for open trades, but it is cleared when a trade is closed (moved to `trades`). The schema was not designed with post-close R:R computation in mind.

**How to avoid:** Two options:
1. **Omit `avg_rr_achieved` from the rolling stats block** — send only `trade_count`, `win_rate`, `avg_net_pnl` per strategy. Claude can still reason about strategy performance without this metric.
2. **Add `initial_stop_loss` column to `trades` table** — requires a Phase 3 schema change. PaperPortfolio's `sell()` / `partial_exit()` must capture `stop_loss` at close time.

The planner must pick one option. Option 1 is lower risk. Option 2 is more informative but requires touching Phase 3 code.

**Warning signs:** `OperationalError: no such column: stop_loss` or a divide-by-zero if you attempt to compute it from known values.

### Pitfall 3: `RISK_PER_TRADE_PCT` Decimal vs Percentage Form

**What goes wrong:** `config.RISK_PER_TRADE_PCT = 0.01` (decimal). If the system prompt embeds this raw value and tells Claude "RISK_PER_TRADE_PCT: 0.01", Claude will treat it as "0.01 percent" and suggest values like 0.012 — which will NEVER trigger the D-07 rejection threshold of `suggested_value > 1.5`.

**Why it happens:** D-07 threshold "suggested_value > 1.5" is calibrated for PERCENTAGE representation (1.5 meaning 1.5%). If the prompt uses decimal form (0.01), the threshold should be 0.015.

**How to avoid:** In the prompt, ALWAYS present `RISK_PER_TRADE_PCT` as `1.0%` (multiply by 100). The `current_value` field of `ParameterChange` should be `config.RISK_PER_TRADE_PCT * 100` = `1.0`. The D-07 threshold `suggested_value > 1.5` then correctly rejects any suggestion over 1.5%.

**Warning signs:** Parameter advisory never fires for RISK_PER_TRADE_PCT, or suggested values are in range 0.005–0.02 instead of 0.5–2.0.

### Pitfall 4: Empty `trades` Table on First Run

**What goes wrong:** If AgentI9 runs before any trades are recorded (e.g., first day of operation, or a no-trade day), the `trades` table may be empty. The rolling stats SQL query returns `None` for aggregate functions (`AVG`, `SUM`) when operating on zero rows.

**Why it happens:** SQLite aggregate functions on empty sets return `NULL`, which becomes `None` in Python.

**How to avoid:** Check for `None` or zero `total_trades` before building the rolling stats block. If no trades exist, pass an empty stats block with a note ("No historical trades in the last 20 days"). The Claude prompt must still be sent — session_verdict of "BREAKEVEN" with no trades is valid.

**Warning signs:** `TypeError: unsupported operand type(s) for /: 'NoneType' and 'int'` when trying to format win_rate percentage.

### Pitfall 5: `review_failed_YYYYMMDD.json` Overwrites If Written Twice

**What goes wrong:** In the partial-failure path (D-04 state 2), both `review_partial_YYYYMMDD.json` AND `review_failed_YYYYMMDD.json` are written. If the code then falls into another error handler that also tries to write `review_failed_YYYYMMDD.json`, it silently overwrites with a less informative error.

**Why it happens:** Python's `Path.write_text()` overwrites existing files without warning.

**How to avoid:** Use a single-exit error path. Set a `_review_state` variable (`"success"` / `"partial"` / `"failed"`) and handle all file writes in one place at the end of `run()`, not inside each `except` block.

---

## Runtime State Inventory

> Omitted — this is a greenfield file creation phase (no rename/refactor involved).

---

## Code Examples

### Agent Class Skeleton

```python
# Source: established project patterns from main.py, CONTEXT.md code_context
from __future__ import annotations
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from pydantic import BaseModel, ValidationError

from config import config
from utils.logger import setup_logger

if TYPE_CHECKING:
    from execution.portfolio import PaperPortfolio

logger = setup_logger(__name__)

PERF_DIR = Path("logs/performance")
DB_PATH = Path("execution/portfolio.db")
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048
TOKEN_CAP = 10_000
CHARS_PER_TOKEN = 4


class ParameterChange(BaseModel):
    param_name: str
    current_value: float
    suggested_value: float
    reason: str


class DailyReview(BaseModel):
    session_verdict: str
    winning_strategies: list[str]
    underperforming_strategies: list[str]
    parameter_adjustments: list[ParameterChange]
    tomorrow_watch: list[str]
    summary: str


class AgentI9:
    def __init__(self, portfolio: PaperPortfolio) -> None:
        self.portfolio = portfolio
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        PERF_DIR.mkdir(parents=True, exist_ok=True)

    def run(self) -> DailyReview | None:
        """Run post-market review. Returns DailyReview on success, None on failure."""
        today_str = date.today().strftime("%Y%m%d")
        # ... implementation
```

### Tabulate Summary in All Three States

```python
# Source: tabulate 0.10.0 verified — tablefmt='grid' works
from tabulate import tabulate

def _print_summary(review: DailyReview | None, state: str, today_str: str) -> None:
    """Print terminal summary regardless of review state."""
    if state == "success" and review is not None:
        rows = [
            [t["symbol"], t["strategy"], t["entry_price"],
             t["exit_price"], t["net_pnl"], t["exit_reason"]]
            for t in today_trades
        ]
        headers = ["Symbol", "Strategy", "Entry", "Exit", "Net P&L", "Reason"]
        print(tabulate(rows, headers=headers, tablefmt="grid", floatfmt=".2f"))
        print(f"\nVerdict: {review.session_verdict}")
        print(f"Summary: {review.summary}")
    elif state == "partial":
        print(f"Partial review — raw text saved to review_partial_{today_str}.json")
    else:
        print(f"Review generation failed — check review_failed_{today_str}.json")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `anthropic.Anthropic().messages.create()` sync | `client.messages.stream()` context manager | anthropic 0.7+ | Partial response capture possible |
| `google-generativeai` SDK | `google-genai>=2.0.0` | Nov 2025 frozen | See STATE.md — Gemini agents use new SDK; Claude agents use `anthropic` directly |
| Pydantic v1 `from pydantic import validator` | Pydantic v2 `from pydantic import field_validator` | Pydantic 2.0 | `BaseModel(**data)` still works; `model_dump_json()` replaces `.json()` |
| `beta` headers for structured outputs | No headers needed | anthropic 0.40+ | Phase 4C uses streaming+manual parse, not structured output — no headers needed either way |

**Deprecated/outdated:**
- `anthropic-beta: structured-outputs-2025-11-13` header: Not needed. Phase 4C uses streaming + manual JSON parse (D-03), not the SDK's `output_format=` structured output feature.
- Pydantic v1 `.json()` method: Replaced by `model_dump_json()` in Pydantic v2.

---

## Open Questions (RESOLVED)

1. **`avg_rr_achieved` in rolling stats (D-09)**
   - What we know: `trades` table does not store `stop_loss`. R:R achieved cannot be computed from existing schema.
   - What's unclear: Does the planner want (a) omit `avg_rr_achieved` from stats block, or (b) add `initial_stop_loss` column to `trades` schema in Phase 3?
   - RESOLVED: Omit `avg_rr_achieved` from rolling stats block. The `trades` table lacks a `stop_loss` column. Plan 04C-02 codifies this by computing only `trade_count`, `win_rate`, and `avg_net_pnl` per strategy. Schema extension deferred to a Phase 3 addendum if needed.

2. **`session_verdict` trust vs inference**
   - What we know: D-06 defines `session_verdict` as `"PROFITABLE"` / `"BREAKEVEN"` / `"LOSS"` — a field Claude fills. CONTEXT.md discretion note says AgentI9 could infer this from `net_pnl` instead.
   - What's unclear: Should AgentI9 override Claude's `session_verdict` with the computed truth from `get_daily_report()` net P&L?
   - RESOLVED: Trust Claude's verdict per CONTEXT.md discretion. No auto-override. Claude's framing (e.g. "BREAKEVEN" despite small positive P&L) is intentionally preserved.

3. **`PaperPortfolio.get_daily_report()` exact return type**
   - What we know: Phase 3 CONTEXT.md D-01 says it "returns full trade ledger with net P&L, win rate, best/worst trade, charges paid" (PORT-08). The exact Python type (list of dicts vs dataclass vs DataFrame) is unspecified — Phase 3 is not yet implemented.
   - What's unclear: AgentI9 must iterate over today's trades to build the prompt. If `get_daily_report()` returns a summary dict rather than a list of individual trades, AgentI9 may need to query `trades` directly for today's ledger too.
   - RESOLVED: `get_daily_report()` must return `list[dict]` of individual closed trade records (keys: symbol, strategy, entry_price, exit_price, qty, gross_pnl, brokerage, net_pnl, exit_reason). Codified as interface contract in Plan 04C-02. Phase 3 implementation must honour this contract.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `anthropic` Python package | Claude Sonnet API call | Yes | 0.86.0 | None — required |
| `pydantic` Python package | DailyReview schema | Yes | 2.12.5 | None — required |
| `tabulate` Python package | Terminal summary | Yes | 0.10.0 | None — required |
| `sqlite3` (stdlib) | Rolling stats query | Yes | stdlib | None — required |
| `execution/portfolio.db` | Trade data source | No (created at runtime by Phase 3) | — | AgentI9 must handle missing DB gracefully |
| `logs/` directory | File output | Yes | exists | `mkdir(parents=True, exist_ok=True)` |
| Anthropic API key | API authentication | Yes (in .env) | — | Raise ValueError with clear message |

**Missing dependencies with no fallback:**
- None. All Python packages are installed. API key existence is a runtime check.

**Missing dependencies with fallback:**
- `execution/portfolio.db` — will not exist until Phase 3 code runs. AgentI9 should handle `sqlite3.OperationalError: no such table: trades` gracefully (return None + write failed sentinel).

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none — see Wave 0 |
| Quick run command | `pytest tests/test_agent_i9.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGNT-13 | Prompt built from trade ledger + 20-day stats; stream called; token count logged | unit (mock anthropic client) | `pytest tests/test_agent_i9.py::test_prompt_construction -x` | No — Wave 0 |
| AGNT-13 | Token cap truncation drops oldest days then time fields | unit | `pytest tests/test_agent_i9.py::test_token_cap_truncation -x` | No — Wave 0 |
| AGNT-14 | Valid JSON response parses into DailyReview | unit | `pytest tests/test_agent_i9.py::test_parse_valid_response -x` | No — Wave 0 |
| AGNT-14 | Partial/invalid JSON written to review_partial file | unit | `pytest tests/test_agent_i9.py::test_partial_response_saved -x` | No — Wave 0 |
| AGNT-15 | MAX_OPEN_POSITIONS raise rejected | unit | `pytest tests/test_agent_i9.py::test_reject_max_positions -x` | No — Wave 0 |
| AGNT-15 | MIN_RISK_REWARD below 1.5 rejected | unit | `pytest tests/test_agent_i9.py::test_reject_min_rr -x` | No — Wave 0 |
| AGNT-15 | RISK_PER_TRADE_PCT above 1.5% rejected | unit | `pytest tests/test_agent_i9.py::test_reject_risk_pct -x` | No — Wave 0 |
| AGNT-16 | review_YYYYMMDD.json written on success | unit | `pytest tests/test_agent_i9.py::test_output_file_success -x` | No — Wave 0 |
| AGNT-16 | review_failed_YYYYMMDD.json written on API exception | unit | `pytest tests/test_agent_i9.py::test_output_file_failure -x` | No — Wave 0 |
| AGNT-16 | Tabulate summary prints in all three states | unit | `pytest tests/test_agent_i9.py::test_terminal_summary -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_agent_i9.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_agent_i9.py` — covers AGNT-13 through AGNT-16
- [ ] `tests/conftest.py` — shared fixtures: mock anthropic client, in-memory SQLite with trades, tmp_path for output files
- [ ] `tests/` directory itself — does not yet exist

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | No | — |
| V4 Access Control | No | — |
| V5 Input Validation | Yes | Pydantic `DailyReview` validates all Claude output; parameter_adjustments validated via D-07 rules |
| V6 Cryptography | No | — |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via trade data | Tampering | System prompt clearly instructs JSON-only response; Claude output validated through Pydantic before use |
| API key exposure in logs | Info Disclosure | `config.ANTHROPIC_API_KEY` read from .env; never logged; `.env` in `.gitignore` (SCAF-05) |
| Malicious `suggested_value` in parameter_adjustments | Tampering | D-07 three-rule auto-reject validation before any downstream use |
| Path traversal in output filenames | Tampering | Filename constructed from `date.today().strftime('%Y%m%d')` — no user input in path |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `PaperPortfolio.get_daily_report()` returns `list[dict]` of individual trade records | Architecture Patterns, Pattern 3 | If it returns a summary dict, AgentI9 must also query today's trades directly from SQLite |
| A2 | `execution/portfolio.db` file location is at project root relative path `execution/portfolio.db` | Pattern 3 code example | If path differs, SQLite connection fails silently (opens new DB) |
| A3 | The `trades` table exists by the time Phase 4C runs | Environment Availability | If Phase 3 hasn't been run, `OperationalError: no such table` — needs graceful handling |

---

## Sources

### Primary (HIGH confidence)
- `anthropic 0.86.0` installed package — source-inspected `MessageStream`, `MessageStreamManager`, `Message`, `Usage`; all streaming APIs and exception types verified
- `pydantic 2.12.5` installed package — `BaseModel`, `ValidationError`, `model_dump_json()` verified via live test
- `config.py` project file — `MAX_OPEN_POSITIONS`, `MIN_RISK_REWARD`, `MIN_RR_RATIO`, `RISK_PER_TRADE_PCT`, `ANTHROPIC_API_KEY` attribute names verified
- `.planning/phases/03-paper-portfolio-engine/03-CONTEXT.md` D-01 — `trades` table schema (all 12 column names)
- `.planning/phases/04C-post-market-agent/04C-CONTEXT.md` — all locked decisions D-01 through D-11
- `utils/logger.py` — `setup_logger(__name__)` pattern confirmed
- `sqlite3` stdlib — rolling stats query and overall totals query verified against in-memory DB

### Secondary (MEDIUM confidence)
- `tabulate 0.10.0` — `tablefmt='grid'` and `floatfmt=` verified via live execution
- `requirements.txt` — confirmed all Phase 4C dependencies already present, no new installs needed

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified via `pip show` and live Python tests
- Architecture: HIGH — streaming pattern source-inspected in anthropic 0.86.0; SQLite patterns verified
- Pitfalls: HIGH for Pitfall 1 (source inspection), HIGH for Pitfall 3 (config.py verified), MEDIUM for Pitfall 2 (inferred from schema gap)

**Research date:** 2026-06-06
**Valid until:** 2026-07-06 (stable libraries; anthropic SDK updates monthly but streaming API surface is stable)
