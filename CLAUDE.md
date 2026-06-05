<!-- GSD:project-start source:PROJECT.md -->
## Project

**nexus_trader**

nexus_trader is a fully automated NSE India intraday paper trading system built in Python. It scans Nifty 100 stocks for gap opportunities each morning, builds a ranked watchlist using Gemini Flash AI and rule-based filters, simulates buy/sell orders throughout the trading day using yfinance data, and reviews performance after market close with Claude Sonnet. Zero real money — 100% simulated with Zerodha-style brokerage math.

**Core Value:** A reliable daily paper trading pipeline that wakes up at 8:30 AM IST, runs without intervention through 3:30 PM, and produces a reviewed trade ledger — proving the strategy logic works before any real capital is risked.

### Constraints

- **Data**: yfinance only — no paid APIs, no WebSocket, no broker feeds
- **Capital**: ₹1,00,000 paper starting capital
- **Risk**: 1% risk per trade, max 5 open positions, max 15 trades/day, 2% daily loss limit halts trading
- **Entry window**: No new entries after 14:00 IST; no entries in first 15 min (before 09:30)
- **Min R:R**: 1.5 — trades below this are filtered out
- **Gap filter**: 1.5%–8.0% gap, prev volume ≥ 500k, price ₹50–₹5000
- **Tech stack**: Python 3.11+, yfinance 0.2.40, pandas, numpy, ta, APScheduler, google-generativeai, anthropic, colorlog, tabulate, pytz
- **Security**: .env for API keys, .gitignore must exclude .env
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Critical Pre-Read: SDK Deprecation Warning
## 1. yfinance
### Known Breaking Changes in 0.2.x (relevant to 0.2.40)
| Change | Impact |
|--------|--------|
| `Ticker.history()` `actions` parameter renamed | Code using old param names breaks silently |
| Multi-ticker `yf.download()` returns MultiIndex columns by default | `.xs()` or `droplevel` needed to flatten |
| `auto_adjust=True` became the default | OHLC values are adjusted; pass `auto_adjust=False` to get raw prices |
| `prepost=False` default | Pre/post market data excluded unless explicitly requested |
| Timezone handling regression (issue #2612) | NSE symbols occasionally trigger `datetime - str` type error causing "symbol may be delisted" false positive |
### NSE (.NS) Specific Issues
### Rate Limiting Behavior
- Sustained requests at > 1 req/sec trigger HTTP 429 within 30–120 seconds
- 429 responses are returned as empty DataFrames by yfinance (no exception raised by default)
- A 0.2-second `time.sleep()` between sequential Ticker calls is the community consensus minimum
- The project's stated 60-second polling interval for live data keeps well below the threshold
### Version Pin Rationale
## 2. APScheduler
### Correct IST Timezone Configuration on Windows
### Recommended Scheduler Type for nexus_trader
- `BlockingScheduler` occupies the main thread — prevents the trading session loop from running
- `AsyncIOScheduler` requires an asyncio event loop; on Windows, asyncio uses `ProactorEventLoop`
- `BackgroundScheduler` with a `ThreadPoolExecutor` is the simplest and most reliable option
### CronTrigger Pattern for NSE Hours
# Pre-market scan at 08:30 IST, Mon-Fri
# Market session poll every 60 seconds, 09:15-15:15 IST
# Post-market review at 15:35 IST
### NSE Holiday Handling
### Windows-Specific Notes
- No Windows-specific APScheduler configuration is required for timezone or cron triggers
- If running inside a process that also uses `asyncio.run()`, keep the scheduler on its own
- `BlockingScheduler.shutdown()` from a signal handler is problematic on Windows (no SIGTERM);
## 3. google-generativeai / google-genai (Gemini Flash)
### Deprecation Timeline
| Date | Event |
|------|-------|
| 2025-02-xx | `google-genai` (unified SDK) released as replacement |
| 2025-08-31 | `google-generativeai` support deadline (originally stated) |
| 2025-11-30 | Development frozen — critical bug fixes only |
| 2026-06-24 | `google-cloud-aiplatform` generative AI module deprecated |
### Migration: Old vs New
### Correct Pattern for JSON Structured Output (Gemini Flash)
# Parse result
# Or use response.parsed if schema was a Pydantic model directly
### Model Names for 2026
| Model ID | Use |
|----------|-----|
| `gemini-2.0-flash` | Fast, cost-effective — recommended for pre-market agents |
| `gemini-2.5-flash` | Improved reasoning, slightly slower |
| `gemini-1.5-flash` | Legacy; still works but prefer 2.0+ |
### Error Handling Pattern
### Requirements.txt Entry
## 4. anthropic SDK (Claude Sonnet)
### Structured JSON Output Patterns
- `output_format` accepts the Pydantic class directly (not an instance)
- `response.parsed_output` is a validated Pydantic instance
- No beta headers required (the old `anthropic-beta: structured-outputs-2025-11-13` header
- The `output_format` parameter is internally translated to `output_config.format` by the SDK
### Recommendation for nexus_trader
### Model Name
## 5. ta (Technical Analysis Library)
### Compatibility Issues with pandas 2.x
| Issue | Severity | Affected Area |
|-------|----------|---------------|
| Positional indexing via `Series[int]` deprecated | HIGH — raises `FutureWarning`, will be `IndexError` in pandas 3.x | `trend.py` line ~1030 and others |
| `fillna(inplace=True)` on chained slice triggers `FutureWarning` | MEDIUM — functions but pollutes logs | Multiple indicator functions |
| `DataFrame.append()` removed in pandas 2.0 | HIGH if any internal usage present — `AttributeError` | Not confirmed in ta 0.11.0 specifically |
| `downcast` param in `fillna()` deprecated (pandas 2.1+) | LOW — warning only in 2.1, error in 3.0 | Downstream if ta outputs passed to fillna |
- Issue #357: "Deprecation Warning from pandas in your library: use of positional indexing in Series" (Aug 2025)
- Issue #348: "FutureWarning at line 1030 (Python 3.12)" (Nov 2024)
- Issue #354: "Incorrect Series Indexing in trend.py line 1030" (Feb 2025)
### Mitigation Options
# requirements.txt
### Recommendation
## 6. Supporting Libraries
### colorlog
### tabulate
### pytz
## 7. Free Fallback Data Sources for NSE (yfinance backup)
| Library | Status | Coverage | Notes |
|---------|--------|----------|-------|
| `nselib` (PyPI) | Active, 2024 updates | Historical EOD, bhav copy, VIX | No intraday; useful for pre-market EOD data |
| `nsetools` (PyPI) | Semi-active | Live quotes, index data | Scrapes NSE website; fragile |
| `nsepython` (PyPI) | Active | NSE APIs, derivatives | Better maintained than nsepy |
| `nsepy` (GitHub) | Unmaintained | Historical data | NSE deprecated old website; broken |
| `nse-data-reader` (PyPI) | Active (nsepy fork) | Historical data | Created specifically as nsepy successor |
## 8. Full Dependency List with Version Pins
# requirements.txt for nexus_trader
# Data
# Scheduling
# AI SDKs
# Technical Analysis
# Data processing
# Output / logging
# Environment
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
