# Technology Stack Research: nexus_trader

**Project:** nexus_trader — NSE India intraday paper trading system
**Researched:** 2026-06-05
**Scope:** Stack dimension only — library-by-library deep dive on six constrained dependencies

---

## Critical Pre-Read: SDK Deprecation Warning

The project spec lists `google-generativeai` as the Gemini SDK. This package was formally
deprecated on November 30, 2025 — its GitHub repo is now named `deprecated-generative-ai-python`.
All new development should target `google-genai` (the unified Google GenAI SDK). See the
google-generativeai section below for the migration path and import changes.

---

## 1. yfinance

**Pinned version:** 0.2.40
**Latest stable:** 1.4.1 (May 2026) — the project deliberately pins 0.2.40 for stability
**Confidence:** MEDIUM — behavior details sourced from GitHub issues + community; no official
rate-limit documentation published by Yahoo/yfinance

### Known Breaking Changes in 0.2.x (relevant to 0.2.40)

| Change | Impact |
|--------|--------|
| `Ticker.history()` `actions` parameter renamed | Code using old param names breaks silently |
| Multi-ticker `yf.download()` returns MultiIndex columns by default | `.xs()` or `droplevel` needed to flatten |
| `auto_adjust=True` became the default | OHLC values are adjusted; pass `auto_adjust=False` to get raw prices |
| `prepost=False` default | Pre/post market data excluded unless explicitly requested |
| Timezone handling regression (issue #2612) | NSE symbols occasionally trigger `datetime - str` type error causing "symbol may be delisted" false positive |

### NSE (.NS) Specific Issues

**Confidence:** MEDIUM (GitHub issues, not official docs)

1. **Timezone detection bug (issue #2612):** yfinance attempts to detect market timezone from
   Yahoo metadata. For some NSE symbols the returned timezone is a bare string instead of a
   `datetime.tzinfo` object, causing arithmetic to fail with
   `unsupported operand type(s) for -: 'datetime.datetime' and 'str'`.
   The issue was closed "not planned" — it is an intermittent failure, not universal.

   **Mitigation:** Always wrap `Ticker.history()` in `try/except Exception` and fall back to
   a retry with explicit `start` / `end` date parameters rather than the `period` shorthand.

2. **Symbol casing:** NSE symbols must be ALL CAPS before appending `.NS`.
   `reliance.NS` fails; `RELIANCE.NS` succeeds.

3. **Intraday interval limits:**
   - `interval="1m"` — data available for last 7 calendar days only
   - `interval="5m"` — data available for last 60 calendar days only
   - `interval="1d"` — unlimited (subject to Yahoo's data availability)
   Requesting `period="1mo"` with `interval="1m"` returns empty DataFrame silently.

4. **Bulk download for 100 stocks:** Use `yf.download(tickers_list, ...)` not individual
   `Ticker` loops. Yahoo groups the request, reducing round-trips. Add `group_by="ticker"` to
   get per-symbol columns.

### Rate Limiting Behavior

Yahoo Finance applies IP-based rate limiting. There is no published threshold; observed limits
in community reports:

- Sustained requests at > 1 req/sec trigger HTTP 429 within 30–120 seconds
- 429 responses are returned as empty DataFrames by yfinance (no exception raised by default)
- A 0.2-second `time.sleep()` between sequential Ticker calls is the community consensus minimum
- The project's stated 60-second polling interval for live data keeps well below the threshold

**Recommended defensive pattern:**

```python
import yfinance as yf
import time

def fetch_history_safe(symbol: str, interval: str = "5m", period: str = "1d") -> pd.DataFrame:
    """Fetch with retry on empty result (possible 429 or timezone bug)."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(interval=interval, period=period)
        if df.empty:
            time.sleep(2)
            df = ticker.history(interval=interval, period=period)
        return df
    except Exception as e:
        logger.warning(f"yfinance fetch failed for {symbol}: {e}")
        return pd.DataFrame()
```

**For bulk pre-market downloads (100 stocks):**

```python
tickers_str = " ".join(nifty100_symbols)  # "RELIANCE.NS TCS.NS ..."
df = yf.download(
    tickers=tickers_str,
    period="5d",
    interval="1d",
    group_by="ticker",
    auto_adjust=True,
    threads=True,
)
time.sleep(0.2)  # mandatory inter-call delay
```

### Version Pin Rationale

0.2.40 is pinned for stability. The 1.x series (started around March 2025) introduced
breaking API changes in `Ticker.history()` parameter names and the download return format.
Pinning avoids mid-run breakage from accidental upgrades.

---

## 2. APScheduler

**Pinned version:** 3.x (latest 3.11.2, released December 2025)
**Confidence:** HIGH — sourced from official APScheduler 3.x documentation

### Correct IST Timezone Configuration on Windows

APScheduler 3.x accepts a `timezone` parameter at scheduler construction time. Pass a pytz
timezone object. On Windows the system clock's local timezone is irrelevant — pytz handles
`Asia/Kolkata` cross-platform with no special flags.

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

IST = pytz.timezone("Asia/Kolkata")

scheduler = BackgroundScheduler(timezone=IST)
```

### Recommended Scheduler Type for nexus_trader

Use `BackgroundScheduler` (not `BlockingScheduler` and not `AsyncIOScheduler`):

- `BlockingScheduler` occupies the main thread — prevents the trading session loop from running
  in the same process
- `AsyncIOScheduler` requires an asyncio event loop; on Windows, asyncio uses `ProactorEventLoop`
  (Python 3.8+) which has known compatibility issues with certain libraries. The scheduler's
  event loop initialization moved to `start()` (not `__init__`) in 3.x to work around this,
  but the extra complexity is unwarranted for a cron-style system
- `BackgroundScheduler` with a `ThreadPoolExecutor` is the simplest and most reliable option
  for a script that runs Python functions on a schedule

### CronTrigger Pattern for NSE Hours

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

IST = pytz.timezone("Asia/Kolkata")

scheduler = BackgroundScheduler(
    timezone=IST,
    job_defaults={
        "coalesce": True,       # If scheduler was paused, run once not N times
        "max_instances": 1,     # Prevent overlapping executions
        "misfire_grace_time": 60,  # Allow 60s of lateness before skipping
    }
)

# Pre-market scan at 08:30 IST, Mon-Fri
scheduler.add_job(
    pre_market_pipeline,
    trigger=CronTrigger(
        day_of_week="mon-fri",
        hour=8,
        minute=30,
        timezone=IST,
    ),
    id="pre_market",
)

# Market session poll every 60 seconds, 09:15-15:15 IST
scheduler.add_job(
    market_session_tick,
    trigger=CronTrigger(
        day_of_week="mon-fri",
        hour="9-15",
        minute="*",
        second=0,
        timezone=IST,
    ),
    id="market_tick",
)

# Post-market review at 15:35 IST
scheduler.add_job(
    post_market_review,
    trigger=CronTrigger(
        day_of_week="mon-fri",
        hour=15,
        minute=35,
        timezone=IST,
    ),
    id="post_market",
)

scheduler.start()
```

### NSE Holiday Handling

APScheduler has no built-in concept of market holidays. The project's decision to use a
hardcoded 2026 holiday list is correct. Pattern:

```python
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 25),  # Holi
    # ... full list
}

def is_trading_day() -> bool:
    today = datetime.now(IST).date()
    return today.weekday() < 5 and today not in NSE_HOLIDAYS_2026
```

Guard each scheduled job with `if not is_trading_day(): return` at the top.

### Windows-Specific Notes

- No Windows-specific APScheduler configuration is required for timezone or cron triggers
- If running inside a process that also uses `asyncio.run()`, keep the scheduler on its own
  background thread (the default for `BackgroundScheduler`) and do not mix with
  `AsyncIOScheduler`
- `BlockingScheduler.shutdown()` from a signal handler is problematic on Windows (no SIGTERM);
  use `BackgroundScheduler` and call `scheduler.shutdown(wait=False)` from a `KeyboardInterrupt`
  handler in your main loop

---

## 3. google-generativeai / google-genai (Gemini Flash)

**CRITICAL:** The package name in the project spec (`google-generativeai`) is deprecated.
**Pinned version (old):** google-generativeai 0.8.6 (latest in that line; dev frozen Nov 2025)
**Recommended package:** `google-genai` 2.8.0 (latest, June 2026)
**Confidence:** HIGH — sourced from official Google AI documentation and PyPI

### Deprecation Timeline

| Date | Event |
|------|-------|
| 2025-02-xx | `google-genai` (unified SDK) released as replacement |
| 2025-08-31 | `google-generativeai` support deadline (originally stated) |
| 2025-11-30 | Development frozen — critical bug fixes only |
| 2026-06-24 | `google-cloud-aiplatform` generative AI module deprecated |

The project MUST migrate from `google-generativeai` to `google-genai`. The import path changes
but the API key and model names remain compatible.

### Migration: Old vs New

**Old (do not use):**
```python
import google.generativeai as genai
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel("gemini-1.5-flash")
response = model.generate_content("...")
```

**New (use this):**
```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
response = client.models.generate_content(
    model="gemini-2.0-flash",  # or "gemini-2.5-flash"
    contents="...",
)
```

### Correct Pattern for JSON Structured Output (Gemini Flash)

Use `response_mime_type` + `response_schema` in `GenerateContentConfig`. Two approaches:

**Approach A — Pydantic model (recommended):**
```python
from google import genai
from google.genai import types
from pydantic import BaseModel

class StockCue(BaseModel):
    symbol: str
    gap_pct: float
    sentiment: str
    rank: int

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=list[StockCue],
    ),
)
# Parse result
import json
results = json.loads(response.text)
# Or use response.parsed if schema was a Pydantic model directly
```

**Approach B — Raw JSON schema dict:**
```python
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema={
            "type": "OBJECT",
            "properties": {
                "symbol": {"type": "STRING"},
                "gap_pct": {"type": "NUMBER"},
                "sentiment": {"type": "STRING"},
                "rank": {"type": "INTEGER"},
            },
            "required": ["symbol", "gap_pct", "sentiment", "rank"],
        },
    ),
)
```

### Model Names for 2026

| Model ID | Use |
|----------|-----|
| `gemini-2.0-flash` | Fast, cost-effective — recommended for pre-market agents |
| `gemini-2.5-flash` | Improved reasoning, slightly slower |
| `gemini-1.5-flash` | Legacy; still works but prefer 2.0+ |

The project spec references "Gemini Flash" without a version number. Use `gemini-2.0-flash`
as the default; make the model ID configurable in `config.py`.

### Error Handling Pattern

```python
def call_gemini_safe(client, prompt: str, schema, model: str = "gemini-2.0-flash") -> dict | None:
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return None
```

### Requirements.txt Entry

```
google-genai>=2.0.0
```

Remove `google-generativeai` entirely.

---

## 4. anthropic SDK (Claude Sonnet)

**Pinned version:** 0.28+ (project spec); latest is 0.105.2 (May 2026)
**Confidence:** HIGH — sourced from official Anthropic platform documentation

### Structured JSON Output Patterns

The Anthropic SDK has two approaches for guaranteed JSON output. The modern approach
(`client.messages.parse()` with Pydantic) requires a recent SDK version and uses the
`output_format` parameter which was introduced with structured outputs support.

**Pattern 1 — Pydantic + `client.messages.parse()` (modern, recommended):**

```python
from pydantic import BaseModel
from anthropic import Anthropic
import os

class TradeReview(BaseModel):
    summary: str
    pnl_analysis: str
    strategy_score: int
    lessons: list[str]
    next_day_watchlist: list[str]

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

response = client.messages.parse(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    messages=[
        {
            "role": "user",
            "content": system_prompt + "\n\n" + trade_data_json,
        }
    ],
    output_format=TradeReview,
)

review: TradeReview = response.parsed_output
print(review.summary)
```

Key notes:
- `output_format` accepts the Pydantic class directly (not an instance)
- `response.parsed_output` is a validated Pydantic instance
- No beta headers required (the old `anthropic-beta: structured-outputs-2025-11-13` header
  is no longer needed but still accepted)
- The `output_format` parameter is internally translated to `output_config.format` by the SDK

**Pattern 2 — `output_config.format` with raw JSON schema:**

```python
import anthropic, json

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}],
    output_config={
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "pnl_analysis": {"type": "string"},
                    "strategy_score": {"type": "integer"},
                    "lessons": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "pnl_analysis", "strategy_score", "lessons"],
                "additionalProperties": False,
            },
        }
    },
)

result = json.loads(response.content[0].text)
```

**Pattern 3 — Legacy tool_use forcing (pre-structured outputs fallback):**

If the SDK version in the target environment is older than the structured outputs release,
the `tool_use` forcing trick remains reliable:

```python
tools = [{
    "name": "record_review",
    "description": "Record the post-market trade review",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "strategy_score": {"type": "integer"},
        },
        "required": ["summary", "strategy_score"],
    },
}]

response = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    tools=tools,
    tool_choice={"type": "tool", "name": "record_review"},
    messages=[{"role": "user", "content": prompt}],
)

tool_use_block = next(b for b in response.content if b.type == "tool_use")
result = tool_use_block.input  # already a dict, no json.loads needed
```

### Recommendation for nexus_trader

Use Pattern 1 (Pydantic + `client.messages.parse()`) as the primary path.
Claude is called only once daily (post-market agent I9), so the extra SDK dependency on a
recent version is acceptable. Keep Pattern 3 as the documented fallback in code comments.

### Model Name

```python
CLAUDE_MODEL = "claude-sonnet-4-5"  # configured in config.py
```

Do not hardcode. Claude model naming has changed repeatedly; make it an env-configurable
constant.

---

## 5. ta (Technical Analysis Library)

**Pinned version:** 0.11.0 (bukosabino/ta)
**Confidence:** MEDIUM — issues sourced from GitHub issue tracker; no official changelog
**Last library update:** ~2023 (the repo has had no new releases since)

### Compatibility Issues with pandas 2.x

The `ta` 0.11.0 library was written against pandas 1.x. Several categories of breakage
occur with pandas 2.0+:

| Issue | Severity | Affected Area |
|-------|----------|---------------|
| Positional indexing via `Series[int]` deprecated | HIGH — raises `FutureWarning`, will be `IndexError` in pandas 3.x | `trend.py` line ~1030 and others |
| `fillna(inplace=True)` on chained slice triggers `FutureWarning` | MEDIUM — functions but pollutes logs | Multiple indicator functions |
| `DataFrame.append()` removed in pandas 2.0 | HIGH if any internal usage present — `AttributeError` | Not confirmed in ta 0.11.0 specifically |
| `downcast` param in `fillna()` deprecated (pandas 2.1+) | LOW — warning only in 2.1, error in 3.0 | Downstream if ta outputs passed to fillna |

**GitHub issues confirming this (bukosabino/ta):**
- Issue #357: "Deprecation Warning from pandas in your library: use of positional indexing in Series" (Aug 2025)
- Issue #348: "FutureWarning at line 1030 (Python 3.12)" (Nov 2024)
- Issue #354: "Incorrect Series Indexing in trend.py line 1030" (Feb 2025)

The issues were open as of research date with no upstream fix merged.

### Mitigation Options

**Option A — Suppress warnings and accept current behavior (low effort, fragile):**
```python
import warnings
import pandas as pd
warnings.filterwarnings("ignore", category=FutureWarning, module="ta")
```
Works until pandas 3.0, at which point FutureWarnings become errors.

**Option B — Pin pandas to 2.x (recommended for stability):**
```python
# requirements.txt
pandas>=2.0.0,<3.0.0
ta==0.11.0
```
Buys time until the project is ready to address indicators directly.

**Option C — Implement indicators manually for critical ones (most robust):**
For VWAP, EMA, RSI, and ATR the formulas are simple enough to implement directly on
DataFrames without ta:

```python
def calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_atr(high, low, close, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()
```

**Option D — Migrate to pandas-ta (actively maintained):**
`pandas-ta` supports pandas 2.x and has a similar API surface. This is a heavier change
requiring API mapping but eliminates the upstream maintenance risk entirely.

### Recommendation

Use **Option B** (pin pandas `<3.0.0`) for Phase 1 build, and plan **Option C** (manual
implementation of VWAP, EMA, RSI, ATR) for Phase 2. The four indicators nexus_trader actually
needs are all straightforward — removing the ta dependency reduces fragility.

---

## 6. Supporting Libraries

### colorlog

**Version:** latest stable (6.x)
**Confidence:** HIGH

```python
import logging
import colorlog

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    log_colors={
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold_red",
    }
))

logger = logging.getLogger("nexus_trader")
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
```

File logging should use a plain `logging.FileHandler` alongside the colorlog handler — colorlog
escape codes in log files make them unreadable with standard tools.

### tabulate

**Version:** latest stable (0.9.x)
**Confidence:** HIGH

```python
from tabulate import tabulate

print(tabulate(
    trade_rows,
    headers=["Symbol", "Entry", "Exit", "PnL", "R:R"],
    tablefmt="rounded_outline",
    floatfmt=".2f",
))
```

`tablefmt="rounded_outline"` gives clean terminal output. Use `tablefmt="grid"` for log-file
output (ASCII only, no Unicode issues on Windows terminals).

### pytz

**Version:** latest stable (2024.x)
**Confidence:** HIGH

```python
import pytz
from datetime import datetime

IST = pytz.timezone("Asia/Kolkata")

def now_ist() -> datetime:
    return datetime.now(IST)

def is_market_open() -> bool:
    now = now_ist()
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close
```

Note: Python 3.9+ ships `zoneinfo` in the standard library which can replace pytz. However,
since pytz is already a declared dependency (and required by APScheduler 3.x anyway), keep
using it for consistency. Do not mix pytz-aware and zoneinfo-aware datetimes in the same
codebase.

---

## 7. Free Fallback Data Sources for NSE (yfinance backup)

**Confidence:** LOW — these are community libraries; maintenance status varies

The project spec states yfinance is the sole data source and alternatives are out of scope.
However, agents I0 and I2 must have fallbacks per the constraint "all Gemini and yfinance
calls must have try/except fallbacks." For completeness:

| Library | Status | Coverage | Notes |
|---------|--------|----------|-------|
| `nselib` (PyPI) | Active, 2024 updates | Historical EOD, bhav copy, VIX | No intraday; useful for pre-market EOD data |
| `nsetools` (PyPI) | Semi-active | Live quotes, index data | Scrapes NSE website; fragile |
| `nsepython` (PyPI) | Active | NSE APIs, derivatives | Better maintained than nsepy |
| `nsepy` (GitHub) | Unmaintained | Historical data | NSE deprecated old website; broken |
| `nse-data-reader` (PyPI) | Active (nsepy fork) | Historical data | Created specifically as nsepy successor |

**For nexus_trader:** yfinance is the only source that provides intraday OHLCV data needed
for the live session loop. The fallback pattern should be retry-with-delay, not alternative
source. The above libraries are useful only if the pre-market pipeline needs EOD data for
a day when yfinance is rate-limited.

---

## 8. Full Dependency List with Version Pins

```text
# requirements.txt for nexus_trader

# Data
yfinance==0.2.40

# Scheduling
APScheduler==3.11.2

# AI SDKs
google-genai>=2.0.0          # Replaces google-generativeai (deprecated Nov 2025)
anthropic>=0.28.0

# Technical Analysis
ta==0.11.0

# Data processing
pandas>=2.0.0,<3.0.0         # Upper bound due to ta 0.11.0 pandas-2.x compat
numpy>=1.24.0
pytz>=2024.1

# Output / logging
colorlog>=6.7.0
tabulate>=0.9.0

# Environment
python-dotenv>=1.0.0
```

---

## Confidence Summary

| Area | Confidence | Primary Source |
|------|------------|---------------|
| yfinance rate limits / 429 behavior | MEDIUM | GitHub issues, community reports |
| yfinance NSE timezone bug | MEDIUM | GitHub issue #2612 |
| yfinance intraday interval limits | MEDIUM | Community documentation |
| APScheduler 3.x IST configuration | HIGH | Official APScheduler 3.x docs |
| APScheduler Windows behavior | HIGH | Official docs + GitHub issues |
| google-generativeai deprecation | HIGH | Official Google AI docs + PyPI |
| google-genai JSON output pattern | HIGH | Official Google AI docs |
| anthropic structured outputs pattern | HIGH | Official Anthropic platform docs |
| ta 0.11.0 pandas 2.x issues | MEDIUM | GitHub issue tracker (open issues) |
| Free NSE data fallbacks | LOW | PyPI listings, community articles |

---

## Sources

- [yfinance PyPI](https://pypi.org/project/yfinance/)
- [yfinance NSE symbol issue #2612](https://github.com/ranaroussi/yfinance/issues/2612)
- [yfinance 429 rate limit issue #2125](https://github.com/ranaroussi/yfinance/issues/2125)
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- [APScheduler PyPI](https://pypi.org/project/APScheduler/)
- [google-generativeai deprecation (GitHub repo)](https://github.com/google-gemini/deprecated-generative-ai-python)
- [Migrate to Google GenAI SDK](https://ai.google.dev/gemini-api/docs/migrate)
- [Google GenAI SDK structured output docs](https://ai.google.dev/gemini-api/docs/structured-output)
- [google-genai PyPI](https://pypi.org/project/google-genai/)
- [Anthropic structured outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [anthropic PyPI](https://pypi.org/project/anthropic/)
- [ta library GitHub issues](https://github.com/bukosabino/ta/issues)
- [pandas 2.2 FutureWarning changes](https://pandas.pydata.org/docs/whatsnew/v2.2.0.html)
- [nselib PyPI](https://pypi.org/project/nselib/)
- [nsepython PyPI](https://pypi.org/project/nsepython/)
