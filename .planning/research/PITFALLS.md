# Domain Pitfalls: nexus_trader

**Domain:** Automated NSE intraday paper trading system (Python, yfinance, APScheduler, Gemini/Claude)
**Researched:** 2026-06-05
**Confidence:** MEDIUM — most findings verified across multiple sources; yfinance behavior confirmed via GitHub issues; some edge cases (pre-open exact behavior, Claude cold-start timing) are LOW confidence single-source

---

## Critical Pitfalls

Mistakes that cause silent wrong results, misleading backtests, or total pipeline failure.

---

### Pitfall C1: yfinance Returns 15-Minute Delayed Quotes for NSE Stocks

**What goes wrong:**
Yahoo Finance serves NSE stock quotes with a 15-minute delay for non-authenticated free-tier users. The `exchangeDataDelayedBy: 15` field is embedded in the API response. When `ticker.history(period="1d", interval="1m")` or `ticker.fast_info.last_price` is called during the 9:15–15:30 market session, the price returned is the price from 15 minutes ago — not the current price. A trade "entered at ₹500" may actually reflect ₹487 live conditions.

**Why it happens:**
NSE charges fees for real-time data. Yahoo Finance does not have a real-time agreement — it provides delayed snapshots. yfinance wraps this without surfacing the delay to the caller. There is no built-in warning; the DataFrame looks identical whether data is live or stale.

**Consequences:**
- Gap signals computed at 8:30 AM using the pre-open indicative price may be based on data that is actually from 8:15 AM
- Intraday fill prices recorded in the paper ledger are not what a real trader would have seen
- Stop-loss monitoring checks a stale price — a halt or spike that hit SL 14 minutes ago is invisible to the monitor loop
- Performance review metrics are systematically optimistic (fills at prices never actually available)

**Warning signs:**
- `ticker.info.get("exchangeDataDelayedBy")` returns `15`
- Recorded fill prices consistently differ from what charting platforms show at the same timestamp
- Intraday candles fetched at 10:00 AM only show bars up to 9:45 AM

**Prevention:**
- Log the delay value from `ticker.info["exchangeDataDelayedBy"]` at startup and write it into every trade record
- Add a mandatory comment in `MarketDataFetcher` docstring: "All prices are up to 15 min delayed — paper trading only"
- Do NOT claim price accuracy beyond the delay window in any performance review; the I9 Claude reviewer prompt must be told data is delayed
- Enforce `prepost=False` in all `history()` calls to avoid mixing pre-market indicative data with regular session data

**Phase to address:** Data layer (Phase 1 / earliest scaffolding). Must be baked into `MarketDataFetcher` before any simulation logic is written.

---

### Pitfall C2: False Gap Signals from Corporate Actions (Ex-Dividend, Bonus, Split)

**What goes wrong:**
The gap screener computes `gap_pct = (today_open - prev_close) / prev_close`. On ex-dividend, ex-bonus, or ex-split dates, `prev_close` in yfinance historical data is adjusted retroactively (when `auto_adjust=True`, the default). However, `today_open` from the intraday 1m candle is the raw market open price — not adjusted. This creates a phantom gap of exactly the corporate action magnitude.

**Specific NSE examples:**
- A 1:1 bonus issue adjusts `prev_close` to half the actual closing price. The screener sees a 100% gap — which passes the 1.5%–8.0% filter as a massive outlier (or the filter rejects it, silently dropping a valid gap-up stock)
- A ₹5 dividend on a ₹100 stock creates a 5% artificial gap-down on ex-date — within the filter range and indistinguishable from a real gap

**Why it happens:**
yfinance `auto_adjust=True` retroactively rewrites all historical OHLCV data when a corporate action occurs. The next-day's opening price from a live intraday call is raw (unadjusted). Mixing adjusted historical close with unadjusted intraday open is the root cause. This is a documented yfinance issue (GitHub #1531, confirmed by PyQuant community).

**Consequences:**
- Screener produces valid-looking gap signals on corporate action days that have zero trading merit
- Historical gap analysis in the backtester systematically misrepresents which days had real gaps

**Warning signs:**
- A stock appears in the gap list on the same day NSE shows it as ex-dividend on its corporate actions calendar
- Gap percentage is suspiciously close to a round number matching a known dividend yield or bonus ratio

**Prevention:**
- Fetch NSE corporate actions calendar daily (from `nseindia.com/companies-listing/corporate-filings-actions`) and cross-reference against the gap list. Any stock appearing on ex-date should be filtered out before ranking.
- Alternatively, use `auto_adjust=False` for `prev_close` fetches and manually apply only the previous session's raw close. This avoids retroactive adjustment contaminating the baseline.
- Add a hard filter: if a symbol's gap_pct is > 9% or < -9%, log it as a suspected corporate action outlier and skip it. The stated filter of 1.5%–8.0% already partially mitigates this but does not catch dividend-range false signals.

**Phase to address:** Gap screener implementation (I1 agent). Must be solved before any live or backtested gap scanning produces results.

---

### Pitfall C3: yfinance Silent Failures Return Empty DataFrames Instead of Raising Exceptions

**What goes wrong:**
When yfinance cannot fetch data (network timeout, symbol temporarily delisted in Yahoo's system, backend issue), it frequently returns an empty DataFrame (`pd.DataFrame()`) with no exception raised. Code that does `df = yf.download("SBIN.NS", ...)` and then accesses `df["Close"].iloc[-1]` raises an `IndexError` deep in application logic — not at the fetch boundary where it could be caught cleanly.

**Confirmed patterns:**
- Valid, actively traded symbols like ITC.NS have been reported as triggering "delisted" exceptions intermittently
- During Yahoo Finance backend instability, `yf.download()` returns an empty DataFrame for valid symbols
- `ticker.history()` returns an empty DataFrame during NSE pre-open (9:00–9:08) because the regular session has not started and `prepost=False` is set

**Why it happens:**
yfinance is a scraper, not an official API. Yahoo Finance can change response formats, authentication tokens, or data availability without notice. The library handles many error cases by returning empty data rather than raising structured exceptions. This was acknowledged in yfinance GitHub #2612 and #2393 as a known behavioral pattern.

**Consequences:**
- Pipeline crashes mid-scan with an unrelated `IndexError` instead of a clean `DataFetchError`
- Partial scan: 40 of 100 stocks succeed before Yahoo rate-limits the session; the remaining 60 are silently missing from the gap list
- If `prev_close` is None due to empty fetch, `gap_pct` computation produces NaN, which can silently pass numeric comparisons depending on pandas behavior

**Warning signs:**
- `len(df) == 0` after a `yf.download()` call
- `df.empty` is True
- `ticker.fast_info.last_price` raises `AttributeError` or returns `None`

**Prevention:**
- Every yfinance call must be wrapped with a guard: `if df is None or df.empty: log_warning(); return None`
- Implement a `DataFetchResult` wrapper that makes fetch failures explicit: `{success: bool, data: DataFrame | None, symbol: str, error: str}`
- Log the count of successful vs. failed fetches per scan cycle; alert if failure rate > 10%
- Use `yf.download(symbols, group_by='ticker')` for bulk fetch of all 100 symbols in one request rather than 100 individual `ticker.history()` calls — reduces failure surface and is less likely to trigger rate limiting

**Phase to address:** Data layer (Phase 1). This is a foundational guard that all other agents depend on.

---

### Pitfall C4: Rate Limiting Causes Silent Partial Scans

**What goes wrong:**
Yahoo Finance enforces rate limits via HTTP 429 responses. In yfinance 0.2.40+, this raises `YFRateLimitError`. However, in bulk `yf.download()` calls, some symbols succeed before the limit is hit and some fail silently. The result is a gap list built from a random 60% of the universe with no indication that the other 40% were not evaluated.

**Pattern specific to nexus_trader:**
The 8:30 AM pre-market scan fetches 100 stocks (I1 gap screener) plus market breadth data (I0 global cues) within a 30-minute window. Without the mandated 0.2s inter-call delay this creates burst traffic. Even with the delay, the full 100-stock scan at 0.2s spacing takes ~20 seconds minimum — acceptable — but if re-runs are triggered (e.g., after exception handling), the second burst hits 429.

**Consequences:**
- Gap list is built on a partial universe — the best opportunity may be in the skipped stocks
- No error is surfaced to the user; the pipeline continues with partial data

**Warning signs:**
- `YFRateLimitError` in logs
- HTTP response metadata containing `"Too Many Requests"`
- `yf.download()` returns data for fewer symbols than requested (check column count)

**Prevention:**
- Implement exponential backoff with jitter: catch `YFRateLimitError`, sleep `min(60, 2^attempt + random(0,1))` seconds, retry up to 3 times
- Cache the previous scan's data so that a rate-limited re-run can use yesterday's data for missing symbols as fallback
- Check `df.columns.get_level_values(1).unique()` after bulk download to detect which symbols actually returned data
- Stagger bulk downloads: do not fetch all 100 at once; split into batches of 20 with 1s between batches

**Phase to address:** Data layer and I1 screener. Rate limit handling must be in place before any multi-symbol scanning is implemented.

---

## Moderate Pitfalls

---

### Pitfall M1: Pre-Open Session (9:00–9:15) Price Data is Indicative, Not Executable

**What goes wrong:**
During NSE pre-open (9:00–9:15 IST), the exchange runs a call auction to discover the equilibrium open price. Prices quoted during this window are indicative — they represent where orders are stacked, not where trades have executed. If yfinance is polled for a 1m candle during this window with `prepost=True`, the returned price may be the indicative price from the call auction, which can differ from the actual 9:15 market open by 0.5%–3%.

**Why it matters for nexus_trader:**
The project constraint says "no new entries before 09:30." However, the gap screener runs at 8:30 AM and uses `prev_close` from historical data. If any component accidentally polls live price during 9:00–9:15 to "validate" the gap, it will use the indicative price — which may not match the actual open, making the gap calculation wrong.

**Consequences:**
- A stock that looks like a 3% gap-up at 9:10 AM may open at only 1.8% at 9:15 (below the 1.5% threshold)
- Conversely, a stock that looks borderline at 9:10 may open strongly, missing it

**Warning signs:**
- Any `ticker.history()` call made between 9:00 and 9:15 IST using `prepost=True`
- Gap percentage computed from a price fetched before 9:15 AM that differs from the 9:15 open

**Prevention:**
- All live price fetches during the pre-market pipeline (8:30–9:00) must use historical data only (`period="2d"`, `interval="1d"`) — never live intraday candles
- The 9:15 market open confirmation should be the first live intraday candle fetch, not before
- Add a time-gate in `MarketDataFetcher`: if called before 9:20 IST, raise a warning and return the previous day's close, not a live quote

**Phase to address:** I1 gap screener and market session transition logic (pre-market pipeline).

---

### Pitfall M2: Stop-Loss / Target Overshoot on Gap Candles — Unrealistic Fill Simulation

**What goes wrong:**
Paper trading commonly simulates fill at exactly the target or stop-loss price. In reality — and especially for NSE intraday — price frequently gaps past these levels within a single 60-second candle. A position with SL at ₹490 may see the next fetched price at ₹483 after news hits. Simulating a fill at ₹490 overstates performance by ₹7/share.

**NSE-specific factors that amplify this:**
- NSE circuit breakers can move a stock's price limit by 2%–20% in one session, meaning a price can jump past SL in one print
- Nifty 100 stocks are liquid but mid-caps in the universe can have spread of ₹1–₹5
- The 60-second polling interval means a 3% spike can be fully missed — the candle's high and low tell you the range, but not the sequence

**Why it matters for nexus_trader:**
If the backtester and live paper engine both simulate exact fills, performance metrics will be systematically optimistic. A strategy showing 2.1% daily return may be -0.3% after realistic slippage.

**Realistic NSE intraday slippage estimates (Nifty 100 equities):**
- Large caps (RELIANCE, TCS, HDFC): 0.02%–0.05% one-way (1–3 ticks)
- Mid-cap in universe: 0.05%–0.15% one-way
- On-circuit / gap-candle fills: can be 0.3%–1.5% away from trigger price

**Prevention:**
- Implement three fill models in `PaperPortfolio`:
  1. `EXACT`: fill at trigger price (optimistic baseline)
  2. `SLIPPAGE_PCT`: fill at trigger ± configurable slippage % (default 0.05%)
  3. `WORST_CANDLE`: if candle low (for longs) goes below SL, fill at candle low — simulates gap-through
- Default to `SLIPPAGE_PCT` for targets, `WORST_CANDLE` for stop-losses
- Log which fill model was used for every order so the I9 reviewer can compare modes

**Phase to address:** PaperPortfolio engine implementation. Must be decided early — changing fill models after data collection invalidates all prior paper results.

---

### Pitfall M3: yfinance Historical Data Breaks After HDFCBANK-Style Corporate Restructurings

**What goes wrong:**
When NSE companies undergo mergers, demergers, or major restructurings (e.g., HDFCBANK + HDFC merger in 2023), yfinance's adjusted historical prices become unreliable for months afterward. The adjustment multipliers are applied incorrectly, producing completely wrong OHLCV data for the pre-merger period. This is confirmed in the yfinance community as causing 2+ years of incorrect backtest returns.

**Why it matters:**
nexus_trader's backtester fetches historical data to replay through strategy logic. If a Nifty 100 component has gone through a restructuring, the backtester's signals and P&L for that stock will be wrong — and the error will not be obvious because the data looks valid.

**Prevention:**
- Maintain a hardcoded list of "unreliable history" symbols: stocks that have undergone restructuring within the past 3 years (e.g., HDFCBANK post-merger, any recent demerger)
- For these symbols, cap the backtest lookback period to post-restructuring dates only
- During backtester development, cross-verify 5 random historical candles per symbol against a known source (NSE Bhavcopy archives) before trusting the backtest output

**Phase to address:** Backtester implementation.

---

### Pitfall M4: Gemini Flash Rate Limits Hit During Multi-Agent Pre-Market Pipeline

**What goes wrong:**
The pre-market pipeline between 8:30 and 9:00 AM runs agents I0 (global cues), I2 (news filter), and I3 (watchlist ranker) sequentially or in parallel — all using Gemini Flash. Free tier limits for Gemini Flash are 15 RPM (requests per minute) and 1,500 RPM for paid Tier 1. However, all four dimensions are independently enforced: RPM, TPM (tokens per minute), RPD (requests per day), and IPM. A prompt that is large (e.g., sending 100 stock descriptions to I3) can exhaust TPM even if RPM is fine.

**Google's documented behavior:**
On December 7, 2025, Google reduced quotas with minimal notice. Free-tier TPM limits were cut, causing previously working applications to return 429 errors. This can recur.

**Consequences:**
- I2 news filter is mid-scan when the 429 hits — returns partial results silently if not properly handled
- I3 ranker receives a truncated watchlist because I2 failed
- Pipeline logs show "success" because exceptions were caught but fallback returned empty list

**Warning signs:**
- `google.api_core.exceptions.ResourceExhausted` in logs
- API response containing `"RESOURCE_EXHAUSTED"` or status 429
- Gemini response time consistently > 8 seconds (approaching timeout)

**Prevention:**
- Wrap every Gemini call in retry logic: catch `ResourceExhausted`, wait 60 seconds, retry once; on second failure, proceed with rule-based fallback
- Split large prompts: do not send all 100 stocks in one I3 call; batch into groups of 20–25
- Monitor token counts per call with `response.usage_metadata`; log tokens consumed to detect quota pressure before hitting the wall
- Define a `GeminiFallbackMode`: if Gemini is unavailable, I3 falls back to a deterministic rule-based ranker using gap_pct, volume, and sector momentum — the pipeline must never halt waiting for an AI response

**Phase to address:** I0, I2, I3 agent implementations. Fallback mode is critical and must be built alongside the primary path.

---

### Pitfall M5: Claude Sonnet I9 Review at 15:30 — Cold Start + Large Context Timeout

**What goes wrong:**
The I9 post-market review runs once at 15:30 IST. It sends the full day's trade ledger, position log, and market context to Claude Sonnet 4.5. Two timing risks:

1. **Cold start**: The Anthropic API may have higher TTFT (time-to-first-token) for the first request of the day from this client. Observed TTFT in GitHub issues ranges from 3–15 seconds before streaming begins, which is acceptable. But if the payload is large and network latency is high from India, total response time can approach or exceed a 60-second timeout.

2. **Large context**: If `max_trades_per_day = 15` and each trade has full metadata, the I9 prompt can easily reach 8,000–15,000 tokens. Claude Sonnet processes these fine, but cost and latency both scale linearly with input tokens.

**Consequences:**
- If I9 times out, the day's review is lost — the trade ledger exists but has no narrative analysis
- If the timeout is not handled, the APScheduler job hangs, holding a thread until the next scheduled job tries to fire

**Prevention:**
- Set an explicit `timeout=120` (2 minutes) on the `anthropic.Anthropic().messages.create()` call; this is well within normal response time but protects against hangs
- Use streaming (`stream=True`) for I9 — write the review incrementally to a file as tokens arrive; partial review is better than no review
- Cap the trade ledger sent to I9: summarize positions rather than sending raw OHLCV data; keep prompt under 10,000 tokens
- If I9 fails, write a sentinel file (`review_failed_YYYYMMDD.json`) so the operator knows review is missing without needing to grep logs

**Phase to address:** I9 agent implementation.

---

### Pitfall M6: APScheduler Job Overlap — Pre-Market Scan Running at 9:15 Market Open

**What goes wrong:**
The 8:30 AM pre-market pipeline job (I0 → I1 → I2 → I3 → watchlist preparation) has no enforced timeout. If Gemini calls are slow, yfinance fetches retry on 429s, or the data processing loop is slow, this job can still be executing when APScheduler fires the 9:15 AM market-open job. By default, APScheduler's `ThreadPoolExecutor` will run both jobs concurrently if `max_instances` is not set to 1.

**Consequences:**
- The watchlist isn't finalized when the 9:15 job tries to read it — race condition, `KeyError` or empty watchlist
- Both jobs share `NexusTrader` state simultaneously — position limits, cash balance, and order log can be corrupted
- The market monitor loop starts processing signals before gap analysis is complete

**Warning signs:**
- "Job missed" or "Job skipped" messages in APScheduler logs
- `max_instances` not explicitly set in `add_job()` calls

**Prevention:**
- Set `max_instances=1` on every job to prevent overlap. APScheduler will skip the new fire if the previous instance is still running and log a "missed execution" warning
- Add a hard timeout to the pre-market pipeline: wrap the entire function in `concurrent.futures.ThreadPoolExecutor` with `timeout=25*60` (25 minutes), so it cannot run past 8:55 AM
- Use a shared `asyncio.Event` or `threading.Event` called `watchlist_ready` that the 9:15 job checks before proceeding; if not set, it waits up to 60 seconds then proceeds with an empty watchlist and logs `CRITICAL: Watchlist not ready at market open`
- Log job start/end timestamps with duration; alert if pre-market job takes > 20 minutes

**Phase to address:** Scheduler implementation and `NexusTrader` orchestrator.

---

## Minor Pitfalls

---

### Pitfall Mi1: APScheduler on Windows — System Clock and pytz Interaction

**What goes wrong:**
APScheduler v3.x uses `pytz` for timezone-aware scheduling. On Windows, the system clock resolution can cause sub-second firing inaccuracies. More critically, if `CronTrigger` is initialized without an explicit `timezone` parameter, it defaults to the system timezone — which on a Windows machine set to a non-IST locale will cause all jobs to fire at the wrong local time. Asia/Kolkata does not observe DST, so DST-transition issues are not a concern, but the system-timezone default trap is real.

**Warning signs:**
- Jobs fire at unexpected times (e.g., 3:00 AM instead of 8:30 AM) on first deploy
- `CronTrigger.from_crontab("30 8 * * 1-5")` without `timezone=IST` specified

**Prevention:**
- Always pass `timezone=pytz.timezone("Asia/Kolkata")` explicitly to every `CronTrigger` and `BackgroundScheduler(timezone=...)` constructor
- Add a startup check: log `scheduler.timezone` and the next fire time for every job; verify manually before leaving the system unattended
- Use `pendulum` instead of `pytz` if timezone handling becomes complex — pendulum has more reliable cross-platform behavior

**Phase to address:** Scheduler implementation.

---

### Pitfall Mi2: NSE Circuit Breaker Stocks — yfinance Returns Frozen Last-Traded Price

**What goes wrong:**
When a stock hits its upper or lower circuit limit on NSE, trading is suspended for that session. yfinance will return the circuit-limit price as the "current price" for the remainder of the session because that is the last traded price. There are no further candles. The system has no native way to know the stock is halted.

**Consequences:**
- Intraday position monitor sees the price as static — it correctly does not trigger SL or target
- If a long position was entered before circuit was hit, the system holds the position, which is correct behavior
- The 15:15 force square-off will simulate a sell at the circuit price — which is realistic for paper trading but should be flagged as "circuit exit"

**Prevention:**
- If a stock's price has not changed in 3 consecutive 60-second polls during regular market hours, flag it as `POSSIBLE_CIRCUIT`
- Log the flag; the I9 reviewer should be told to note circuit exits in the performance review
- Do not attempt new entries in a `POSSIBLE_CIRCUIT` stock

**Phase to address:** Position monitor (I6 agent).

---

### Pitfall Mi3: NSE Holiday List Staleness

**What goes wrong:**
The project uses a hardcoded NSE 2026 holiday list. NSE occasionally adds or moves trading holidays with short notice (e.g., election days, national mourning). If the list is stale, the scheduler fires on a market holiday, the pre-market scan runs, and the pipeline attempts to trade on a day with no market activity.

**Consequences:**
- yfinance returns the previous session's data for the "today" scan — all stocks appear to have large gaps because the last trade was two days ago
- All stocks pass the gap filter with exaggerated percentages
- Trades are simulated against stale prices; the trade ledger shows activity on a non-trading day

**Warning signs:**
- Market depth is zero on NSE's website for the day
- yfinance returns 0 volume for all symbols in the first intraday candle

**Prevention:**
- Add a pre-market check: fetch the Nifty 50 index (`^NSEI`) 1m candle at 8:30 AM; if volume is 0, abort and log "Market appears closed — aborting scan"
- Cross-reference against the hardcoded list AND the zero-volume check — neither alone is sufficient
- Update the holiday list at the start of each calendar quarter by checking the NSE official holiday calendar

**Phase to address:** Scheduler + pre-market pipeline startup check.

---

### Pitfall Mi4: Entry Time Constraint Race Condition at 14:00 Cutoff

**What goes wrong:**
The constraint "no new entries after 14:00 IST" is implemented as a time check in the signal engine. If the market session loop fires at 13:59:55 IST and the signal generation + order placement takes 8 seconds, the order is placed at 14:00:03 — after the cutoff. The time check passes at the start of the function but the actual order is submitted past 14:00.

**Prevention:**
- Check the cutoff at the point of order submission, not at the start of signal evaluation
- Use `datetime.now(IST) < cutoff_time` in `PaperPortfolio.buy()` as a guard, not just in the calling code

**Phase to address:** PaperPortfolio engine and signal engine integration.

---

## Phase-Specific Warnings

| Phase / Component | Likely Pitfall | Mitigation |
|-------------------|---------------|------------|
| Data layer (Phase 1) | C3 silent empty DataFrame | Wrap every fetch; guard `df.empty` before any `.iloc` access |
| Data layer (Phase 1) | C1 15-min delay | Document in `MarketDataFetcher`; log delay value at startup |
| Data layer (Phase 1) | C4 rate limiting | 0.2s inter-call delay + `YFRateLimitError` exponential backoff |
| I1 gap screener | C2 false gap from corporate actions | Filter ex-date symbols; validate with `auto_adjust=False` for prev_close |
| I1 gap screener | M1 pre-open indicative price | Never fetch live intraday before 9:15; use daily historical for prev_close |
| I0/I2/I3 Gemini agents | M4 rate limit / 429 / TPM exhaustion | Retry + fallback to rule-based ranking built in parallel |
| PaperPortfolio | M2 SL/target overshoot | `WORST_CANDLE` fill model for stop-losses by default |
| Position monitor (I6) | Mi2 circuit breaker frozen price | 3-poll static-price detection → `POSSIBLE_CIRCUIT` flag |
| I9 Claude reviewer | M5 cold start / timeout | `timeout=120`, streaming, prompt under 10K tokens |
| APScheduler | M6 job overlap | `max_instances=1` on all jobs; `watchlist_ready` event gate |
| APScheduler | Mi1 Windows timezone | Explicit `timezone=pytz.timezone("Asia/Kolkata")` on every trigger |
| Scheduler startup | Mi3 holiday list staleness | Zero-volume abort check on `^NSEI` at 8:30 AM |
| Backtester | M3 restructuring history | Hardcoded "unreliable history" symbol list with post-restructuring date caps |
| Signal engine / portfolio | Mi4 14:00 entry cutoff race | Time guard at point of order submission, not at signal evaluation |

---

## Sources

- yfinance NSE data accuracy issues: [GitHub #2055](https://github.com/ranaroussi/yfinance/issues/2055), [GitHub #2612](https://github.com/ranaroussi/yfinance/issues/2612), [GitHub #2393](https://github.com/ranaroussi/yfinance/issues/2393)
- yfinance rate limiting: [GitHub #2125](https://github.com/ranaroussi/yfinance/issues/2125), [GitHub #2422](https://github.com/ranaroussi/yfinance/issues/2422)
- yfinance auto_adjust / corporate action gaps: [GitHub #1531](https://github.com/ranaroussi/yfinance/issues/1531), [Medium: Adj Close disappeared](https://medium.com/@josue.monte/why-adj-close-disappeared-in-yfinance-and-how-to-adapt-6baebf1939f6)
- Yahoo Finance NSE 15-minute delay confirmed: [Marketcalls.in API exploration](https://www.marketcalls.in/intraday/exploring-yahoo-finance-realtime-quotes-and-historical-data-feed-api.html), [NSE delayed data tariff](https://nsearchives.nseindia.com/s3fs-public/inline-files/Download%2015%20mins%20delayed%20data%20tariff.pdf)
- NSE pre-open session mechanics: [Zerodha support](https://support.zerodha.com/category/trading-and-markets/trading-faqs/market-sessions/articles/what-are-pre-market-and-post-market-sessions-and-orders), [Groww pre-open explainer](https://groww.in/blog/what-is-pre-open-market-session-in-the-stock-market)
- NSE circuit breakers: [NSE India official](https://www.nseindia.com/products-services/equity-market-circuit-breakers)
- NSE corporate actions and price adjustment: [NSE corporate filings](https://www.nseindia.com/companies-listing/corporate-filings-actions), [Niftytrader bonus adjustment](https://www.niftytrader.in/markets/trent-ex-bonus-stock-drop-adjustment/)
- Gemini API rate limits: [Google AI rate limits docs](https://ai.google.dev/gemini-api/docs/rate-limits), [AI Free API rate limit guide](https://www.aifreeapi.com/en/posts/gemini-api-rate-limit-explained)
- Claude API latency: [Anthropic latency docs](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency)
- APScheduler job overlap and timezone: [APScheduler docs](https://apscheduler.readthedocs.io/en/3.x/userguide.html), [GitHub #346](https://github.com/agronholm/apscheduler/issues/346), [GitHub #370](https://github.com/agronholm/apscheduler/issues/370)
- Realistic slippage and fill simulation: [AlgoTest blog](https://algotest.in/blog/best-virtual-trading-apps-in-india/), [Lares Algotech slippage explainer](https://laresalgotech.com/what-is-slippage-in-trading-meaning-examples/)
