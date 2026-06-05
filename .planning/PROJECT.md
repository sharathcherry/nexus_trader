# nexus_trader

## What This Is

nexus_trader is a fully automated NSE India intraday paper trading system built in Python. It scans Nifty 100 stocks for gap opportunities each morning, builds a ranked watchlist using Gemini Flash AI and rule-based filters, simulates buy/sell orders throughout the trading day using yfinance data, and reviews performance after market close with Claude Sonnet. Zero real money — 100% simulated with Zerodha-style brokerage math.

## Core Value

A reliable daily paper trading pipeline that wakes up at 8:30 AM IST, runs without intervention through 3:30 PM, and produces a reviewed trade ledger — proving the strategy logic works before any real capital is risked.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Project scaffolding: nexus_trader/ folder structure, config.py, requirements.txt, .env.example
- [ ] Data layer: MarketDataFetcher (yfinance), Indicators (VWAP/EMA/RSI/ATR/ORB), NSE universe (100 stocks)
- [ ] Paper portfolio engine: PaperPortfolio (buy/sell/partial_exit/trailing SL), OrderManager (position sizing)
- [ ] 7 trading agents: I0 global cues, I1 gap screener, I2 news filter, I3 watchlist ranker, I4 signal engine, I6 position monitor, I9 Claude reviewer
- [ ] Main orchestrator: NexusTrader class, async pre-market pipeline, market session loop
- [ ] Scheduler: APScheduler IST, Mon–Fri, NSE 2026 holiday-aware
- [ ] Structured logger: colorlog terminal + file output
- [ ] Dry-run mode: --dry-run CLI flag runs pre-market pipeline on yesterday's data
- [ ] Backtester: NexusBacktester, replays historical data through strategy logic
- [ ] README: setup guide, run modes, API key instructions

### Out of Scope

- Real broker API integration — paper trading only; no Zerodha/Upstox/Angel API
- Live order execution — all trades simulated
- Real-time WebSocket data — yfinance polling only (60-second minimum interval)
- Mobile app or web UI — terminal output only
- Paid data feeds — yfinance is the sole data source
- Short selling simulation — long-only for v1
- Options/futures — equity cash segment only

## Context

- Data source: yfinance exclusively. All symbols use .NS suffix. 60s minimum poll interval enforced by yfinance rate limits. 0.2s delay between bulk API calls required.
- APIs: Gemini Flash (pre-market agents I0 + I2), Claude Sonnet 4.5 (post-market agent I9 only).
- IST timezone throughout: APScheduler configured with Asia/Kolkata.
- Market hours: 09:15–15:30 IST. Pre-market scan: 08:30–09:00. Force square-off: 15:15.
- Brokerage simulation: Zerodha intraday — min(₹20, 0.03% turnover) + STT 0.025% sell-side + exchange charges 0.00335% + 18% GST on brokerage.
- Universe: 100 Nifty stocks hardcoded with .NS suffix and sector tags.
- All Gemini and yfinance calls must have try/except fallbacks — APIs fail silently.

## Constraints

- **Data**: yfinance only — no paid APIs, no WebSocket, no broker feeds
- **Capital**: ₹1,00,000 paper starting capital
- **Risk**: 1% risk per trade, max 5 open positions, max 15 trades/day, 2% daily loss limit halts trading
- **Entry window**: No new entries after 14:00 IST; no entries in first 15 min (before 09:30)
- **Min R:R**: 1.5 — trades below this are filtered out
- **Gap filter**: 1.5%–8.0% gap, prev volume ≥ 500k, price ₹50–₹5000
- **Tech stack**: Python 3.11+, yfinance 0.2.40, pandas, numpy, ta, APScheduler, google-generativeai, anthropic, colorlog, tabulate, pytz
- **Security**: .env for API keys, .gitignore must exclude .env

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| yfinance-only data | Zero cost, sufficient for paper trading simulation | — Pending |
| Gemini Flash for pre-market AI | Fast inference needed at 8:30–9:00 AM; cost-effective | — Pending |
| Claude Sonnet for post-market review only | Deep analysis needed; runs once daily at 3:30 PM | — Pending |
| 60-second polling interval | yfinance rate limit constraint; acceptable for paper trading | — Pending |
| Zerodha-style brokerage math | Realistic cost simulation without real account | — Pending |
| Long-only positions v1 | Simplifies risk model; short-selling adds complexity | — Pending |
| Hardcoded NSE 2026 holiday list | APScheduler needs static list; holiday APIs add dependency | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-05 after initialization*
