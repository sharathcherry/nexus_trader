# Phase 4C: Post-Market Agent - Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 1 new file (agents/agent_i9.py)
**Analogs found:** 3 / 1 (3 structural analogs from plan files and existing source; no compiled agent .py files exist yet)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `agents/agent_i9.py` | service / agent | request-response (Claude API) + batch (SQLite query) | `04B-01-PLAN.md` AgentI6 class skeleton + `04A-PLAN-A.md` AgentI0 skeleton | role-match (same project agent pattern; no compiled .py analog exists) |

---

## Pattern Assignments

### `agents/agent_i9.py` (service/agent, request-response + batch)

**Note on analog availability:** The `agents/` directory contains only `__init__.py` (empty). No compiled agent `.py` files exist in the repo yet — phases 4A and 4B have PLAN files that define the agent class structure but the files have not been written. The patterns below are extracted from:
1. `config.py` (lines 1–57) — `from config import config` import pattern, attribute names
2. `utils/logger.py` (lines 1–54) — `setup_logger(__name__)` pattern
3. `main.py` (lines 1–13) — module-level setup pattern
4. `.planning/phases/04B-market-session-agents/04B-01-PLAN.md` — AgentI6 class structure (closest role match: agent with `__init__(self, portfolio)` + single `run()` / `monitor_positions()` public method)
5. `.planning/phases/04A-pre-market-agents/04A-PLAN-A.md` — AgentI0 class structure (module-level client, `run()` entrypoint, error-returning pattern)
6. `04C-RESEARCH.md` patterns 1–6 — fully verified against installed packages

---

#### Imports pattern

**Source:** `main.py` lines 1–4 + `04B-01-PLAN.md` action block + `04A-PLAN-A.md` action block

```python
from __future__ import annotations
import json
import sqlite3
from collections import deque
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from pydantic import BaseModel, ValidationError
from tabulate import tabulate

from config import config
from utils.logger import setup_logger

if TYPE_CHECKING:
    from execution.portfolio import PaperPortfolio

logger = setup_logger(__name__)
```

Key conventions from `main.py` and plan files:
- `from config import config` at module level (NOT `import config`)
- `logger = setup_logger(__name__)` as module-level singleton (NOT per-call instantiation)
- `TYPE_CHECKING` guard for heavy imports used only in type hints
- `from __future__ import annotations` enables deferred annotation evaluation

---

#### Module-level constants pattern

**Source:** `04A-PLAN-A.md` (AgentI0 module-level client creation) + `04C-RESEARCH.md` Pattern 1

```python
PERF_DIR = Path("logs/performance")
DB_PATH = Path("execution/portfolio.db")
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048
TOKEN_CAP = 10_000
CHARS_PER_TOKEN = 4
```

Convention: uppercase module-level constants, `Path()` objects for all filesystem references.

---

#### Class `__init__` pattern

**Source:** `04B-01-PLAN.md` AgentI6 class structure (lines under "Task 1: action") + `04C-RESEARCH.md` Agent Class Skeleton

```python
class AgentI9:
    def __init__(self, portfolio: PaperPortfolio) -> None:
        self.portfolio = portfolio
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        PERF_DIR.mkdir(parents=True, exist_ok=True)
```

Conventions established in 04B:
- Agent receives `portfolio` as constructor argument (passed by Phase 5 orchestrator)
- Heavy clients (Anthropic, Gemini) created once in `__init__`, stored as `self._client` (private)
- Directory creation done in `__init__` (not at import time)

---

#### Public method signature pattern

**Source:** `04B-01-PLAN.md` AgentI6 interface block + `04A-PLAN-A.md` AgentI0 `run()` doc

```python
def run(self) -> DailyReview | None:
    """Run post-market review. Returns DailyReview on success, None on failure."""
    today_str = date.today().strftime("%Y%m%d")
    ...
```

Conventions:
- Public method named `run()` (matches AgentI0, AgentI4 patterns)
- Returns `Type | None` — `None` on all failure paths (never raises to caller)
- Docstring on all public methods

---

#### Anthropic streaming pattern

**Source:** `04C-RESEARCH.md` Pattern 1 (verified against anthropic 0.86.0 source)

```python
full_text = ""
tokens_used = 0

try:
    with self._client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt_text}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
        # get_final_message() MUST be called inside the with block
        final_msg = stream.get_final_message()
        tokens_used = final_msg.usage.input_tokens + final_msg.usage.output_tokens

    logger.info(f"Claude stream complete — {tokens_used} tokens used")

except anthropic.APIConnectionError as e:
    logger.error(f"Connection error: {e}")
    _review_state = "failed"
    _failure_detail = str(e)
except anthropic.APITimeoutError as e:
    logger.error(f"Timeout: {e}")
    _review_state = "failed"
    _failure_detail = str(e)
except anthropic.RateLimitError as e:
    logger.error(f"Rate limit hit: {e}")
    _review_state = "failed"
    _failure_detail = str(e)
except anthropic.APIStatusError as e:
    logger.error(f"API error {e.status_code}: {e.message}")
    _review_state = "failed"
    _failure_detail = str(e)
```

Critical: `get_final_message()` inside `with` block, after `text_stream` exhausted. See RESEARCH.md Pitfall 1.

---

#### Pydantic schema + parse pattern

**Source:** `04C-RESEARCH.md` Pattern 2 (verified against pydantic 2.12.5)

```python
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


# Parse path (after stream completes):
try:
    data = json.loads(full_text)
    review = DailyReview(**data)
except json.JSONDecodeError as e:
    logger.error(f"JSON parse failed: {e}")
    _review_state = "partial"
except ValidationError as e:
    logger.error(f"Schema validation failed: {e}")
    _review_state = "partial"

# Serialize to file:
(perf_dir / f"review_{today_str}.json").write_text(
    review.model_dump_json(indent=2), encoding="utf-8"
)
```

Conventions (Pydantic v2 specific):
- `model_dump_json()` replaces v1 `.json()` method
- `DailyReview(**data)` constructor from parsed dict
- `ValidationError` from `pydantic` (not `pydantic.v1`)

---

#### SQLite query pattern

**Source:** `04C-RESEARCH.md` Pattern 3 (verified against sqlite3 stdlib + Phase 3 schema)

```python
def _get_rolling_stats(self, days: int = 20) -> dict:
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

Conventions:
- `conn.row_factory = sqlite3.Row` enables column-name access
- `try/finally: conn.close()` — always close connection even on exception
- Named parameters `{"days": f"-{days} days"}` — avoid SQL injection and f-string fragility
- Handle empty result: check `totals` for `None` before `dict()` call

---

#### Three-state output / file persistence pattern

**Source:** `04C-RESEARCH.md` Pattern 4 (verified against pathlib stdlib)

```python
today_str = date.today().strftime("%Y%m%d")
perf_dir = Path("logs/performance")
perf_dir.mkdir(parents=True, exist_ok=True)

# Single-exit file write — set _review_state variable, write in one place
if _review_state == "success":
    (perf_dir / f"review_{today_str}.json").write_text(
        review.model_dump_json(indent=2), encoding="utf-8"
    )
elif _review_state == "partial":
    (perf_dir / f"review_partial_{today_str}.json").write_text(
        full_text, encoding="utf-8"
    )
    (perf_dir / f"review_failed_{today_str}.json").write_text(
        json.dumps({"error": "json_parse_failed", "date": today_str}),
        encoding="utf-8",
    )
else:  # "failed"
    (perf_dir / f"review_failed_{today_str}.json").write_text(
        json.dumps({"error": "stream_exception", "date": today_str,
                    "detail": _failure_detail}),
        encoding="utf-8",
    )
```

Convention: Use a `_review_state` variable (`"success"` / `"partial"` / `"failed"`) and write all files in one place at the end of `run()` — prevents the Pitfall 5 overwrite bug (RESEARCH.md).

---

#### Parameter advisory validation pattern

**Source:** `04C-RESEARCH.md` Pattern 5 (verified against config.py attributes)

```python
def _validate_parameter_adjustments(
    self,
    adjustments: list[ParameterChange],
) -> list[ParameterChange]:
    """Remove unsafe parameter suggestions per D-07. Returns cleaned list."""
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
            logger.warning(
                f"Auto-rejected: {adj.param_name} suggestion {adj.suggested_value}% "
                f"exceeds risk ceiling 1.5%"
            )
            rejected = True
        if not rejected:
            valid.append(adj)
    return valid
```

Critical: D-07 threshold `suggested_value > 1.5` assumes the prompt presents RISK_PER_TRADE_PCT in percentage form (1.0%, not 0.01 decimal). The system prompt MUST multiply `config.RISK_PER_TRADE_PCT * 100` before embedding. See RESEARCH.md Pitfall 3.

---

#### Token cap truncation pattern

**Source:** `04C-RESEARCH.md` Pattern 6

```python
TOKEN_CAP = 10_000
CHARS_PER_TOKEN = 4

def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN

# Build prompt from full 20-day window
rolling_stats = self._get_rolling_stats(days=20)
prompt_text = self._build_prompt(today_trades, rolling_stats)

# Progressive truncation
for days in [20, 15, 10]:
    if self._estimate_tokens(prompt_text) <= TOKEN_CAP:
        break
    rolling_stats = self._get_rolling_stats(days=days)
    prompt_text = self._build_prompt(today_trades, rolling_stats)
    logger.warning(f"Prompt truncated to {days}-day window to stay under token cap")

# Final fallback: drop time fields
if self._estimate_tokens(prompt_text) > TOKEN_CAP:
    prompt_text = self._build_prompt(today_trades, rolling_stats, omit_times=True)
    logger.warning("Dropped entry_time/exit_time fields to stay under token cap")

logger.info(f"Prompt estimated tokens: {self._estimate_tokens(prompt_text)}")
```

---

#### Error handling convention

**Source:** `04A-PLAN-A.md` AgentI0 (never raises) + `04B-01-PLAN.md` error pattern

All agent methods follow:
- Return `None` or empty on failure — never raise to caller
- `logger.error(...)` before any early return
- Exception types caught specifically (not bare `except Exception`)
- For the streaming call: 4 specific anthropic exception types caught (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError)
- For SQLite: `sqlite3.OperationalError` (handles missing `trades` table on first run)

```python
# Graceful DB missing table handling
try:
    stats = self._get_rolling_stats()
except sqlite3.OperationalError as e:
    logger.error(f"SQLite error (trades table may not exist yet): {e}")
    stats = {"strategy_breakdown": [], "totals": {}}
```

---

#### Tabulate terminal summary pattern

**Source:** `04C-RESEARCH.md` "Tabulate Summary in All Three States" code example (verified tabulate 0.10.0)

```python
def _print_summary(
    self,
    review: DailyReview | None,
    state: str,
    today_str: str,
    today_trades: list[dict],
) -> None:
    """Print terminal summary in all three states (D-05)."""
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

## Shared Patterns

### Logger instantiation
**Source:** `utils/logger.py` lines 9–54 + `main.py` lines 1–4
**Apply to:** All agent files, any new module

```python
from utils.logger import setup_logger
logger = setup_logger(__name__)
```

`setup_logger(__name__)` returns a logger with both colored terminal output and rotating file handler (`logs/nexus_YYYY-MM-DD.log`). Never create a second logger per call — the function is idempotent (checks `logger.handlers` before adding).

### Config access
**Source:** `config.py` lines 1–57
**Apply to:** All files that read project constants

```python
from config import config
# Access: config.ANTHROPIC_API_KEY, config.MAX_OPEN_POSITIONS,
#         config.MIN_RISK_REWARD, config.RISK_PER_TRADE_PCT
```

All constants are attributes of the singleton `config` instance. Never import individual attributes — always import `config` and access via dot notation. Missing `.env` keys raise `ValueError` at import time.

Verified attribute names for AgentI9:
- `config.ANTHROPIC_API_KEY` — Anthropic API key (string)
- `config.MAX_OPEN_POSITIONS` — 5 (int)
- `config.MIN_RISK_REWARD` — 1.5 (float)
- `config.RISK_PER_TRADE_PCT` — 0.01 (float, decimal — multiply by 100 in prompt)

### Return-None-on-failure contract
**Source:** `04A-PLAN-A.md` AgentI0 spec + `04B-01-PLAN.md` error conventions
**Apply to:** All agent `run()` methods

Every agent's primary entrypoint returns `Type | None`. On any exception: log the error, write any sentinel files, return `None`. Never let exceptions propagate to the caller (Phase 5 orchestrator).

### Path + directory creation
**Source:** `04C-RESEARCH.md` Pattern 4 + `utils/logger.py` line 34
**Apply to:** Any file that creates output directories

```python
Path("logs/performance").mkdir(parents=True, exist_ok=True)
# parents=True creates intermediate dirs if absent
# exist_ok=True is idempotent — safe to call on every __init__
```

---

## No Analog Found

No files in this phase lack analogs — all patterns are covered by existing source files (`config.py`, `utils/logger.py`, `main.py`) and plan files (04A, 04B). The RESEARCH.md code examples are fully verified and serve as primary analog where no compiled `.py` exists.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | All patterns have analogs |

---

## Key Implementation Notes for Planner

1. **No async needed for AgentI9.** Unlike AgentI0/AgentI4 which use `async def run()`, AgentI9 is called once post-market by the Phase 5 orchestrator. `def run()` is synchronous — the Anthropic streaming API is synchronous (`client.messages.stream()` is not `async`).

2. **`avg_rr_achieved` omitted from rolling stats.** The `trades` table (Phase 3 schema) lacks a `stop_loss` column. RESEARCH.md Pitfall 2 documents this gap. The planner must choose Option 1 (omit) or Option 2 (add `initial_stop_loss` column to Phase 3 schema). RESEARCH.md recommends Option 1 for lower risk.

3. **RISK_PER_TRADE_PCT representation in prompt.** `config.RISK_PER_TRADE_PCT = 0.01`. The prompt must present this as `1.0%` (multiply by 100). The D-07 rejection threshold `> 1.5` is calibrated for percentage form. This is the most likely bug if not handled explicitly.

4. **`get_final_message()` placement.** Must be called INSIDE the `with client.messages.stream(...)` block, after `text_stream` is exhausted. RESEARCH.md Pitfall 1 explains why calling it after the block exit causes `AssertionError` on interrupted streams.

5. **Single-exit file write pattern.** Use `_review_state = "success" | "partial" | "failed"` variable and write all files in one consolidated block at the end of `run()`. Avoid writing `review_failed_YYYYMMDD.json` inside multiple exception handlers — RESEARCH.md Pitfall 5.

---

## Metadata

**Analog search scope:** `agents/`, `execution/`, `utils/`, `main.py`, `config.py`, `.planning/phases/04A-*/`, `.planning/phases/04B-*/`
**Files scanned:** 7 source files + 6 plan files
**Pattern extraction date:** 2026-06-06
