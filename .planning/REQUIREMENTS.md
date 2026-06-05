# Requirements: nexus_trader

**Defined:** 2026-06-05
**Core Value:** A reliable daily paper trading pipeline that runs automatically 8:30 AM–3:30 PM IST, simulates NSE intraday trades without real money, and produces a reviewed performance ledger each day.

## v1 Requirements

### Scaffolding

- [ ] **SCAF-01**: Project folder structure matches nexus_trader/ spec (agents/, execution/, data/, utils/, logs/)
- [ ] **SCAF-02**: config.py contains all parameters (capital, risk, gap filters, time windows, API keys via .env)
- [ ] **SCAF-03**: requirements.txt pins all dependencies (yfinance, pandas, numpy, ta, apscheduler, google-generativeai, anthropic, colorlog, tabulate, pytz)
- [ ] **SCAF-04**: .env.example template documents GEMINI_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- [ ] **SCAF-05**: .env is excluded from git via .gitignore

### Data Layer

- [ ] **DATA-01**: NSE universe contains 100 Nifty stocks with .NS suffix and sector classification
- [ ] **DATA-02**: MarketDataFetcher.get_previous_close() fetches prev-day close for a batch of symbols
- [ ] **DATA-03**: MarketDataFetcher.get_premarket_price() returns latest available price per symbol
- [ ] **DATA-04**: MarketDataFetcher.get_intraday_candles() returns 5-min OHLCV DataFrame for today
- [ ] **DATA-05**: MarketDataFetcher.get_historical_data() returns daily OHLCV for backtesting/ATR
- [ ] **DATA-06**: MarketDataFetcher.get_global_indices() fetches S&P 500, NASDAQ, Nikkei, Hang Seng, Crude, Gold, USD/INR
- [ ] **DATA-07**: MarketDataFetcher.get_atr() calculates 14-period ATR from historical daily data
- [ ] **DATA-08**: All MarketDataFetcher methods have try/except and return None/empty on failure
- [ ] **DATA-09**: 0.2s delay enforced between bulk yfinance API calls
- [ ] **DATA-10**: Indicators.vwap() computes session-reset VWAP from OHLCV DataFrame
- [ ] **DATA-11**: Indicators.ema() computes EMA for configurable period and column
- [ ] **DATA-12**: Indicators.rsi() computes RSI with configurable period
- [ ] **DATA-13**: Indicators.atr() returns latest ATR value from DataFrame
- [ ] **DATA-14**: Indicators.orb() returns (orb_high, orb_low) for first N minutes of session
- [ ] **DATA-15**: Indicators.volume_ratio() returns current candle volume / N-candle average

### Paper Portfolio Engine

- [ ] **PORT-01**: PaperPortfolio.buy() validates halted state, max positions, max trade size, daily trade count before placing
- [ ] **PORT-02**: PaperPortfolio.buy() deducts cost from capital and records position with entry metadata
- [ ] **PORT-03**: PaperPortfolio.sell() calculates Zerodha brokerage: min(₹20, 0.03% turnover) + STT 0.025% sell-side + exchange 0.00335% + 18% GST on brokerage
- [ ] **PORT-04**: PaperPortfolio.sell() updates daily_pnl, capital, and checks 2% daily loss limit (sets is_halted)
- [ ] **PORT-05**: PaperPortfolio.partial_exit() exits 50% of position at first target
- [ ] **PORT-06**: PaperPortfolio.update_stop_loss() updates trailing stop loss for open position
- [ ] **PORT-07**: PaperPortfolio.get_portfolio_summary() returns capital, positions, daily P&L, win rate, trade count, halted status
- [ ] **PORT-08**: PaperPortfolio.get_daily_report() returns full trade ledger with net P&L, win rate, best/worst trade, charges paid
- [ ] **PORT-09**: PaperPortfolio saves/loads state to JSON for continuity across days
- [ ] **PORT-10**: Every buy/sell prints colored terminal log (✅ BUY / ❌ SELL / ⚠️ SL HIT) with symbol, price, P&L, reason
- [ ] **PORT-11**: OrderManager.calculate_quantity() sizes position by risk: risk_per_trade / risk_per_share, capped at 10% capital
- [ ] **PORT-12**: OrderManager.check_and_execute_exits() checks target hit, SL hit, 15:15 force square-off every polling cycle
- [ ] **PORT-13**: OrderManager.update_trailing_stops() trails GAP_AND_GO at 0.75 ATR below price once 1 ATR in profit; moves ORB SL to breakeven at 1:1 R:R

### Agents

- [ ] **AGNT-01**: AgentI0 fetches global indices at 8:30 AM, calls Gemini Flash to classify market bias (BULLISH/BEARISH/NEUTRAL), falls back to rule-based if API fails
- [ ] **AGNT-02**: AgentI0 returns bias_strength, gift_nifty_gap_pct, valid_strategies, confidence; overrides to NEUTRAL if confidence < 0.5
- [ ] **AGNT-03**: AgentI1 scans 100-stock universe at 8:45 AM, filters by gap % (1.5–8%), volume ≥ 500k, price ₹50–₹5000
- [ ] **AGNT-04**: AgentI1 applies direction filter from market bias, calculates gap_score, returns top 20 candidates; returns empty list if < 3 found
- [ ] **AGNT-05**: AgentI2 calls Gemini Flash per candidate with recent yfinance news to classify catalyst_type and trade_recommendation
- [ ] **AGNT-06**: AgentI2 removes BLOCK_DEAL / INDEX_REBALANCE gaps and AVOID recommendations; 1s delay between Gemini calls; fallback to UNKNOWN on API failure
- [ ] **AGNT-07**: AgentI3 assigns strategy (GAP_AND_GO / GAP_FILL / ORB_BREAKOUT / VWAP_RECLAIM) and calculates entry_trigger, stop_loss, target per stock
- [ ] **AGNT-08**: AgentI3 filters out stocks with R:R < 1.5, returns top 10 watchlist
- [ ] **AGNT-09**: AgentI4 runs signal detection loop from 9:15 AM to 3:15 PM, polling every 60 seconds
- [ ] **AGNT-10**: AgentI4 gates entries: no new entries before 9:30 AM or after 14:00; checks strategy-specific conditions using live indicators
- [ ] **AGNT-11**: AgentI4.force_squareoff_all() closes all open positions at market price at 15:15 IST
- [ ] **AGNT-12**: AgentI6 monitors open positions each cycle: partial exit at 1:1 R:R, trailing stop updates, hard SL/target checks
- [ ] **AGNT-13**: AgentI9 calls Claude Sonnet at 3:30 PM with full daily trade ledger and 20-day rolling stats
- [ ] **AGNT-14**: AgentI9 parses Claude response: session_verdict, winning/underperforming strategies, parameter_adjustments, tomorrow_watch
- [ ] **AGNT-15**: AgentI9 auto-rejects any Claude suggestion that raises MAX_OPEN_POSITIONS, lowers MIN_RISK_REWARD below 1.5, or raises RISK_PER_TRADE_PCT above 1.5%
- [ ] **AGNT-16**: AgentI9 saves review JSON to logs/performance/ and prints formatted tabulate summary to terminal

### Orchestrator & Scheduler

- [ ] **ORCH-01**: NexusTrader.run_pre_market_pipeline() executes I0→I1→I2→I3 in sequence at correct times, aborts on NO_TRADE_DAY conditions
- [ ] **ORCH-02**: Pre-market pipeline prints formatted watchlist table (symbol, gap%, strategy, R:R, catalyst) before market open
- [ ] **ORCH-03**: NexusTrader.run_market_session() launches AgentI4 signal loop, handles KeyboardInterrupt gracefully
- [ ] **ORCH-04**: NexusTrader.run_post_market() generates daily report and invokes AgentI9 at 3:30 PM, saves portfolio state
- [ ] **ORCH-05**: TradingScheduler runs full pipeline Mon–Fri at 8:30 AM IST, skips NSE 2026 holidays
- [ ] **ORCH-06**: Logger outputs INFO (green), WARNING (yellow), ERROR (red), TRADE (cyan), P&L+/- (bright green/red) to terminal and file
- [ ] **ORCH-07**: main.py prints NEXUS ASCII banner on startup

### Dry-Run & Backtest

- [ ] **TEST-01**: python main.py --dry-run runs full pre-market pipeline on yesterday's data without starting market loop
- [ ] **TEST-02**: --dry-run prints watchlist and exits cleanly with no errors
- [ ] **TEST-03**: NexusBacktester.run() replays each trading day from start_date to end_date — skips weekends and NSE holidays
- [ ] **TEST-04**: Backtester simulates gap scan (open vs prev close), entry conditions, exit conditions (target/SL/EOD) per day
- [ ] **TEST-05**: Backtester returns total_trades, win_rate, total_net_pnl, total_return_pct, sharpe_ratio, max_drawdown_pct, profit_factor, monthly_returns
- [ ] **TEST-06**: python backtest.py --start 2025-01-01 --end 2025-03-31 processes 60+ trading days and prints formatted report
- [ ] **TEST-07**: README.md documents installation, .env setup, three run modes (live/dry-run/backtest), API key sources

## v2 Requirements

### Alerts

- **ALRT-01**: Telegram alerts for trade entries, exits, and daily summary (optional — config toggle)
- **ALRT-02**: Telegram alerts for NO_TRADE_DAY detection

### Extended Universe

- **UNIV-01**: Expand from Nifty 100 to Nifty 500 universe
- **UNIV-02**: Dynamic universe from NSE website (real-time constituent list)

### Short Selling

- **SHRT-01**: Simulate short positions for gap-down candidates
- **SHRT-02**: STT on short-side at 0.025% of sell turnover

### Dashboard

- **DASH-01**: Simple terminal dashboard (curses/rich) showing live positions and P&L
- **DASH-02**: Daily HTML report generation

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real broker API (Zerodha/Upstox/Angel) | Paper trading only — no real order execution |
| Real-time WebSocket data | yfinance only; 60s minimum poll interval |
| Paid data feeds (NSE direct, Bloomberg) | Zero-cost constraint |
| Short selling simulation | v1 long-only to simplify risk model |
| Options/futures trading | Equity cash segment only for v1 |
| Mobile or web UI | Terminal output sufficient for v1 |
| Multi-account portfolio | Single paper account only |
| Live parameter auto-adjustment | Agent I9 suggestions are advisory only — manual apply |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCAF-01 to SCAF-05 | Phase 1 | Pending |
| DATA-01 to DATA-15 | Phase 2 | Pending |
| PORT-01 to PORT-13 | Phase 3 | Pending |
| AGNT-01 to AGNT-08 | Phase 4a | Pending |
| AGNT-09 to AGNT-12 | Phase 4b | Pending |
| AGNT-13 to AGNT-16 | Phase 4c | Pending |
| ORCH-01 to ORCH-07 | Phase 5 | Pending |
| TEST-01 to TEST-07 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 57 total
- Mapped to phases: 57
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-05*
*Last updated: 2026-06-05 after initial definition*
