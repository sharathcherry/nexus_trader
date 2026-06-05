# Feature Landscape: nexus_trader

**Domain:** Automated intraday paper trading system — NSE India gap strategies
**Researched:** 2026-06-05
**Confidence:** HIGH (brokerage math), HIGH (strategies), MEDIUM (gap thresholds), HIGH (indicators)

---

## Research Answers

### Q1. Are GAP_AND_GO and GAP_FILL standard strategies for Indian markets?

YES — both are well-established and widely documented in Indian retail trading:

- **GAP_AND_GO** is described by major Indian brokers (ICICI Direct, Groww, Enrich Money) as "the best intraday strategy for fast-paced trading," based on gap continuation momentum. Entry is on breakout of the first 15-minute candle high with a volume surge. Stop-loss is below the first candle low. It is momentum-driven and suited for gaps backed by news or global cues.

- **GAP_FILL** is equally standard. Indian traders know that "common gaps and exhaustion gaps tend to fill within the same session" (NSE intraday behavior). The fill trade fades the gap, entering as price retraces toward the previous close. Mean-reversion in character.

- **ORB_BREAKOUT** (Opening Range Breakout using the 9:15–9:30 or 9:15–9:45 window) is the single most cited intraday setup in Indian market literature. The NSE open concentrates "the highest institutional order flow of the entire session." ORB high/low are the key intraday S/R levels of the day.

- **VWAP_RECLAIM** is standard institutional-grade. VWAP is used as an execution benchmark by mutual funds, FIIs, and prop desks on NSE, making it a self-fulfilling support/resistance level. A VWAP reclaim triggers short-covering plus momentum buyers simultaneously.

All four strategies are verifiably standard. No research flag needed here.

---

### Q2. Gap % thresholds and volume filters — are 1.5%–8.0% and 500k correct?

MEDIUM confidence (no single authoritative source gives exact retail-standard thresholds; ranges vary by stock type):

**Gap percentage by stock tier:**
- Large-cap (Nifty 50): 0.75%–1.5% minimum is considered meaningful. The 1.5% floor in PROJECT.md is appropriate — it filters noise while catching genuine large-cap gaps.
- Mid/small cap: 2%–4%+ is the standard filter. Since the universe is Nifty 100 (large + mid-cap), 1.5% is the right lower bound.
- The 8.0% upper cap is sound — gaps beyond 8% on large-caps typically indicate circuit-adjacent events, halt risk, or extreme illiquidity on the open. Trading these is high-risk.

**Volume filter:**
- The 500k (5 lakh shares) previous-day volume filter is a standard liquidity gate for NSE intraday screeners.
- Professional screeners additionally apply a first-15-minute volume check: entry candle volume should be at minimum 1.5x the 20-day average for that time window. This is a phase-2 enhancement, not table stakes.
- The ₹50–₹5,000 price filter correctly excludes penny stocks and ultra-high-price stocks where position sizing math breaks down.

**Assessment:** The thresholds in PROJECT.md (1.5%–8.0%, 500k, ₹50–₹5,000) are well-calibrated and match community practice for Nifty 100 stocks. No correction needed.

---

### Q3. Technical indicators — VWAP, EMA, RSI, ATR, ORB — are all essential?

YES — all five are standard, and their combination is the most-cited professional intraday setup in Indian market sources:

| Indicator | Role in nexus_trader | Essentiality |
|-----------|---------------------|--------------|
| **VWAP** | Session fair value, VWAP_RECLAIM signal trigger, institutional benchmark | Table stakes — session anchor |
| **EMA** (9/21) | Trend direction filter, crossover signal confirmation | Table stakes — momentum filter |
| **RSI** | Overbought/oversold filter, entry confirmation (>50 for longs, <50 for shorts) | Table stakes — momentum confirmation |
| **ATR** | Dynamic stop-loss sizing (1.5x–2x ATR from entry to avoid noise) | Table stakes — stops without ATR are arbitrary |
| **ORB** | Defines 9:15–9:30 high/low range for ORB_BREAKOUT strategy | Table stakes — core strategy requires it |

The canonical professional NSE combo is: VWAP for session bias, EMA crossover for trend, RSI for confirmation. ATR for stops. ORB for opening volatility containment. nexus_trader uses exactly this combination. No gaps.

---

### Q4. Position sizing — is 1% risk per trade standard?

YES — the 1% rule is the retail standard and is explicitly cited in Indian trading education:

- "Never risk more than 1-2% of trading capital on a single trade" is the near-universal guideline from SEBI-registered advisors and broker knowledge bases.
- A SEBI 2022 study found 90% of Indian retail traders lose money; poor position sizing is cited as a primary cause.
- For a ₹1,00,000 paper account, 1% = ₹1,000 risk per trade. Position size = ₹1,000 / (entry − stop-loss in ₹ per share).
- Max 5 positions + 2% daily loss halt + max 15 trades/day are conservative, appropriate limits for a Nifty 100 intraday system.

The PROJECT.md position sizing rules are correct and conservatively calibrated.

---

### Q5. Zerodha intraday brokerage math — is the project spec correct?

**Source:** Zerodha official charges page (zerodha.com/charges) verified 2026-06-05.

| Charge | Project Spec | Official Zerodha | Verdict |
|--------|-------------|------------------|---------|
| Brokerage | `min(20, turnover * 0.0003)` | min(₹20, 0.03% of turnover) = min(20, turnover * 0.0003) | CORRECT — 0.03% = 0.0003 |
| STT | `sell_turnover * 0.00025` | 0.025% on sell side = 0.00025 | CORRECT |
| Exchange charges | `total_turnover * 0.0000335` | 0.00307% = 0.0000307 per rupee | DISCREPANCY — see below |
| GST | `brokerage * 0.18` | 18% on (brokerage + SEBI charges + transaction charges) | PARTIALLY CORRECT — see below |
| Stamp duty | Not in spec | 0.003% on buy side | MISSING — minor |
| SEBI charges | Not in spec | ₹10 per crore | MISSING — negligible |

**Exchange charges discrepancy (HIGH confidence):**
The project spec uses `0.0000335` (0.00335%). Zerodha's official page states NSE equity exchange charges are `0.00307%` = `0.0000307`. The project spec is 9% too high. This is a minor simulation inaccuracy — it makes cost estimates slightly more pessimistic than reality, which is conservative and acceptable for a paper trading system.

**GST scope note (MEDIUM confidence):**
Technically, GST is 18% on brokerage + SEBI charges + exchange transaction charges, not just brokerage. However, SEBI charges (₹10/crore) are negligible. Applying GST only to brokerage slightly understates the GST component but the error is less than 1% of total costs. Acceptable for simulation.

**Stamp duty (LOW materiality):**
0.003% on buy-side turnover is missing. On a ₹50,000 buy trade this is ₹1.50. Omitting it makes the simulation 1–3 rupees cheaper per trade than reality. Not worth adding unless exact realism is required.

**Recommendation:** The brokerage math is close enough for a paper trading simulation. The exchange charge rate should be corrected from `0.0000335` to `0.0000307` if exact accuracy is desired, but the current conservative figure is acceptable. Add stamp duty in a future iteration.

---

### Q6. Post-market review metrics — what matters most?

Based on algorithmic trading performance literature and intraday trading evaluation standards:

**Primary metrics (must compute daily):**
1. **Win rate** — percentage of profitable trades. Context: a 40% win rate with 2:1 R:R is profitable; never interpret win rate in isolation.
2. **Profit factor** — gross profits / gross losses. Above 1.3 = viable edge. Above 1.5 = promising. Above 2.0 = strong.
3. **Average R multiple** — average trade P&L expressed in multiples of risk taken. The cleanest normalized metric.
4. **Max drawdown (daily)** — largest equity drop within the session. Compare against the 2% halt threshold.
5. **Average trade cost** — average brokerage + STT + exchange charges per trade. Must be less than average gross profit per trade or the system has no edge.

**Secondary metrics (weekly/cumulative):**
6. **Sharpe ratio** — daily returns / standard deviation. Above 1.0 is acceptable; above 2.0 is strong for intraday.
7. **Expectancy** — (win rate × avg win) − (loss rate × avg loss). Must be positive.
8. **Strategy breakdown** — P&L, win rate, and trade count per strategy (GAP_AND_GO, GAP_FILL, ORB_BREAKOUT, VWAP_RECLAIM) separately.
9. **Time-of-day analysis** — which entry windows (9:30–10:30, 10:30–12:00, 12:00–14:00) produce best results.
10. **Slippage estimate** — difference between signal price and simulated fill price (relevant because yfinance 60s polling means fills are approximated).

**AI reviewer scope (Claude Sonnet I9 agent):**
The AI review should focus on: (a) narrative explanation of why specific trades won or lost, (b) pattern detection across strategy types, (c) market condition context (trending day vs. range-bound day vs. volatile day), (d) recommendation on whether to tighten or loosen filters for next session.

---

## Table Stakes Features

Features that must exist for the system to function as described. Missing any of these = broken product.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Gap scanner (1.5%–8.0%, 500k vol, ₹50–₹5,000 price) | Core entry criterion — without it there is no watchlist | Low | Calculation: (open − prev_close) / prev_close |
| VWAP calculation (session-anchored, resets daily) | Used by two strategies; institutional benchmark | Low | Reset at 09:15 IST daily; cumulative VWAP from first candle |
| EMA (9-period, 21-period) on 1-min and 5-min candles | Trend filter for all four strategies | Low | Standard pandas_ta / ta-lib |
| RSI (14-period) on 5-min candles | Entry confirmation filter | Low | Standard calculation |
| ATR (14-period) on 5-min candles | Stop-loss sizing | Low | Essential — arbitrary stops cause false exits |
| ORB high/low from 09:15–09:30 candles | Required for ORB_BREAKOUT strategy | Low | Store first-15-min high and low per ticker |
| Position sizing: quantity = risk_amount / (entry − stop) | 1% risk per trade enforcement | Low | Rounds down to whole shares |
| Zerodha brokerage math (all 4 components) | Realistic cost simulation | Low | See Q5 above |
| Square-off at 15:15 IST | NSE intraday rule; all positions must close | Low | Forced market-price exit |
| No new entries after 14:00 IST | Standard intraday risk control | Low | Time gate on signal engine |
| No entries in first 15 min (before 09:30) | ORB requires range formation first; opening auction noise | Low | Time gate |
| 2% daily loss halt | Drawdown protection | Low | Check after each exit |
| Max 5 concurrent positions | Concentration risk limit | Low | Position count gate |
| Daily P&L ledger with per-trade detail | Minimum viable output | Low | CSV or structured log |
| Profit factor, win rate, avg R computed daily | Basic performance evaluation | Low | Aggregation math |
| Strategy-level P&L breakdown | Essential for diagnosing which strategies work | Low | Group by strategy enum |
| NSE market holiday awareness (2026 list) | Prevents running on exchange-closed days | Low | Static list acceptable |
| Dry-run / replay mode | Development and testing without waiting for live market | Medium | Replay yesterday's data |

---

## Differentiating Features

Features that distinguish nexus_trader from a basic paper trading script. Not expected by default, but high value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| AI pre-market watchlist ranking (Gemini Flash) | Prioritizes best gap candidates using global cues + news context — human-level filter automation | Medium | I0 + I2 agents; Gemini Flash chosen for speed at 08:30 |
| AI post-market narrative review (Claude Sonnet) | Qualitative pattern recognition across trade history; surfaces insights a metrics dashboard cannot | Medium | I9 agent; runs once daily |
| 4-strategy classification with per-strategy stats | Enables systematic A/B comparison of strategies without manual log parsing | Low | Strategy enum on every trade |
| Trailing stop-loss with partial exit | Locks in profit as trade moves in favor; more realistic than fixed-point exit | Medium | Track high-water mark per position |
| Global cues agent (I0) — pre-market context | SGX Nifty, GIFT Nifty, Dow futures as gap confirmation signal | Medium | Requires reliable morning data source |
| News filter agent (I2) — suppress event-driven gaps | Filters gaps caused by earnings, FDA, M&A news where gap fill logic breaks down | Medium | Pattern matching on headlines |
| Configurable risk parameters via config.py | No hardcoded magic numbers; allows systematic parameter variation | Low | Already planned |
| Backtester (NexusBacktester) | Validates strategies on historical data before live paper trading | High | Replay engine through strategy logic |
| Colorlog structured terminal output | Real-time legible monitoring without a web dashboard | Low | tabulate + colorlog already in stack |
| Time-of-day performance bucketing | Identifies best entry windows (9:30–10:30 vs 12:00–14:00) | Low | Add timestamp bucket to trade log |
| Slippage estimation column | Captures the delta between signal price and 60s-delayed fill; quantifies yfinance polling lag cost | Low | Signal_price vs fill_price in ledger |

---

## Anti-Features

Features to explicitly NOT build in v1. Building these risks scope creep, false complexity, or wasted effort.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real broker API integration (Zerodha Kite, Upstox) | Paper trading goal is strategy validation, not execution. Live API adds auth complexity, SEBI compliance risk, and real money exposure. | Simulate with Zerodha math. Broker API is phase N+2 if at all. |
| WebSocket / tick data | yfinance does not support it; building a workaround creates a fragile, undocumented dependency | Accept 60s polling. Note in system that fills are price-at-next-poll |
| Short selling | Doubles complexity of position model (margin math differs), adds risk of SEBI regulatory rules on intraday short delivery | Long-only v1 is documented decision |
| Options / futures | Entirely different instrument model (lot sizes, expiry, premium decay, Greeks). Out of scope by design. | Out of scope |
| Mobile / web UI | Terminal output is sufficient for a research/simulation system. UI adds frontend stack, auth, hosting. | colorlog + tabulate terminal output |
| Paid data feeds (Quandl, Refinitiv, NSE official feed) | Adds cost and API dependency. yfinance is sufficient for paper trading validation. | yfinance only |
| Multi-broker brokerage simulation | One brokerage model (Zerodha) is enough to validate cost impact. Adding others adds no research value. | Zerodha math only |
| Sentiment analysis from social media (Twitter/Reddit) | Unreliable signal quality for NSE; adds NLP pipeline complexity with no proven edge in this strategy set | Use news filter (I2) on structured news only |
| Machine learning signal generation | Strategy logic should be rule-based for interpretability. ML adds training data requirements, feature engineering, overfitting risk. | Rule-based strategies with AI review, not AI signal generation |
| Portfolio rebalancing / multi-day holding | This is an intraday system. All positions close by 15:15 IST. Multi-day logic is a different product. | Force square-off at 15:15 |
| Live alerting (SMS/email/Telegram) | No real money at risk; terminal logging is sufficient. Alerting adds third-party service dependencies. | Structured logs + daily review |
| Exchange connectivity testing / mock order book | Unnecessary for paper trading. There is no real order book interaction. | Simulate fills at market price |

---

## Feature Dependencies

```
Gap Scanner
  └─> Watchlist (ranked candidates)
        └─> Signal Engine (per-strategy entry logic)
              ├─> GAP_AND_GO: requires ORB high, volume surge
              ├─> GAP_FILL: requires VWAP, gap % direction
              ├─> ORB_BREAKOUT: requires ORB high/low
              └─> VWAP_RECLAIM: requires VWAP, RSI > 50

Signal Engine
  └─> Position Manager (sizing, entry, exit)
        └─> Brokerage Math (cost per trade)
              └─> Trade Ledger (daily P&L)
                    └─> Performance Metrics (daily aggregation)
                          └─> Claude Reviewer I9 (narrative + insight)

Indicators (VWAP, EMA, RSI, ATR, ORB)
  └─> All four strategies depend on subset

Market Data (yfinance)
  └─> Indicators
  └─> Gap Scanner
  └─> Position Monitor (60s tick for trailing SL)

Scheduler (APScheduler IST)
  └─> Pre-market pipeline (08:30–09:00)
  └─> Market session loop (09:15–15:30)
  └─> Force square-off trigger (15:15)
  └─> Post-market review trigger (15:35)

NSE Holiday List
  └─> Scheduler (skip non-trading days)
```

---

## MVP Recommendation

Build in this order — each layer is prerequisite for the next:

1. **Data layer first** — MarketDataFetcher + Indicators (VWAP/EMA/RSI/ATR/ORB). Nothing works without data.
2. **Gap scanner** — core filter that produces the watchlist. Simple arithmetic; validate outputs manually.
3. **Paper portfolio engine** — PaperPortfolio with position sizing, brokerage math, square-off logic. The financial simulation core.
4. **Signal engine** — implement GAP_AND_GO first (simplest momentum logic), then GAP_FILL, then ORB_BREAKOUT, then VWAP_RECLAIM.
5. **Orchestrator + scheduler** — wire everything into the daily pipeline.
6. **Logging + ledger** — structured output so the system is observable.
7. **Performance metrics** — daily aggregation after first successful runs.
8. **AI agents** — Gemini pre-market (I0, I2, I3) and Claude post-market (I9) after rule-based core is stable.
9. **Backtester** — implement last; requires all strategy logic to be finalized first.

Defer: Trailing stop partial-exit (add after basic stops work). Time-of-day bucketing (add to ledger later). Slippage column (log both signal and fill price from day 1 but analysis comes later).

---

## Brokerage Math: Corrected Reference Formula

The PROJECT.md formula is correct in spirit with one minor discrepancy noted:

```python
# Per executed order (buy leg or sell leg separately)
brokerage_per_leg = min(20.0, turnover * 0.0003)          # 0.03% capped at Rs 20

# Applied on both buy and sell legs
total_brokerage = brokerage_buy + brokerage_sell

# STT: sell side only for intraday
stt = sell_turnover * 0.00025                              # 0.025%

# NSE exchange charges: both sides
# Official rate: 0.00307% = 0.0000307 (project spec uses 0.0000335 -- conservative, acceptable)
exchange_charges = total_turnover * 0.0000307              # use this for accuracy

# GST: 18% on brokerage (and technically on exchange charges + SEBI, but negligible)
gst = total_brokerage * 0.18

# Stamp duty (buy side only, often omitted in simulations)
stamp_duty = buy_turnover * 0.00003                        # 0.003%

# SEBI charges (negligible: Rs 10 per crore)
sebi = total_turnover * 0.000001

# Total transaction cost
total_cost = total_brokerage + stt + exchange_charges + gst
# stamp_duty and sebi are optional additions for exactness
```

**Verdict on project spec brokerage math:** The spec formula `min(20, turnover * 0.0003)` is CORRECT. STT at 0.00025 is CORRECT. Exchange charges at 0.0000335 are ~9% overstated vs official 0.0000307 — a minor conservative error acceptable for a paper simulation. GST on brokerage only is a minor understatement. The simulation will underestimate net profitability by a tiny fraction compared to actual Zerodha costs. This is the safer direction for a validation system.

---

## Sources

- Zerodha official charges page: https://zerodha.com/charges/
- Zerodha STT explanation: https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated
- NSE exchange charges (Zerodha support): https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges
- Gap and Go strategy — ICICI Direct: https://www.icicidirect.com/futures-and-options/articles/how-to-seek-benefit-from-price-gaps-the-gap-and-go-intraday-strategy
- Gap and Go — Groww: https://groww.in/blog/gap-and-go-strategy
- Gap trading — Samco: https://www.samco.in/knowledge-center/articles/what-is-gap-trading-how-to-trade-gaps-using-the-right-strategies/
- ORB strategy — Angel One: https://www.angelone.in/knowledge-center/online-share-trading/opening-range-breakout-strategy
- ORB NSE screener: https://www.stockezee.com/stock-screener/technical/price-action/opening-range-breakout
- VWAP reclaim setups: https://www.snappchart.app/blog/strategy-playbooks/vwap-momentum-trading-strategy
- VWAP intraday India 2026: https://stoxra.com/blog/vwap-trading-strategy-beginners-india-intraday
- Best indicators NSE 2026: https://stoxra.com/blog/best-intraday-trading-indicators-used-by-professional-traders-in-india-2026
- Intraday indicators NSE: https://stockmarketmentor.in/trading/intraday-indicators/
- 1% risk rule: https://tradethatswing.com/the-1-risk-rule-for-day-trading-and-swing-trading/
- Position sizing India: https://stockpathshala.com/position-sizing-for-intraday-trading/
- Trading performance metrics: https://www.quantifiedstrategies.com/trading-performance/
- Algorithmic trading metrics: https://tradingwyckoff.com/en/algorithmic-trading/algorithmic-trading-metrics/
- Gap screener NSE: https://bottomstreet.com/screener/gap-up-stocks-nse/
- Nifty gap screener: https://www.niftytrader.in/gap-ups-gap-downs
