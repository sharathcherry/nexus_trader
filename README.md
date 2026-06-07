# nexus_trader

Fully automated NSE India intraday paper trading system. Scans all 100 Nifty stocks for gap opportunities each morning, builds a ranked watchlist using Gemini Flash, simulates buy/sell orders throughout the session using yfinance data, and reviews daily performance with Claude Sonnet.

**Zero real money -- 100% simulated with Zerodha-style brokerage math.**

Starting capital: Rs1,00,000. Max deployment: Rs1,00,000/day (5 positions x Rs20,000).

---

## Deploy on Azure VM (Standard_B1ls or larger)

**1. Clone the repo**
```bash
git clone <your-repo-url> nexus_trader
cd nexus_trader
```

**2. Run setup (one time only)**
```bash
bash setup.sh
```

This script handles everything automatically:
- Adds 1GB swap (required -- 512MB RAM is not enough for pandas alone)
- Installs Python 3.11
- Creates virtualenv and installs all dependencies
- Initialises the portfolio database at Rs1,00,000
- Installs and enables a systemd service for auto-restart on reboot

**3. Add your API keys**
```bash
nano .env
```

Fill in all four values:
```
GEMINI_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=7123456789:AAF...
TELEGRAM_CHAT_ID=123456789
```

| Key | Where to get it |
|-----|----------------|
| GEMINI_API_KEY | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| ANTHROPIC_API_KEY | [Anthropic Console](https://console.anthropic.com/settings/keys) |
| TELEGRAM_BOT_TOKEN | BotFather on Telegram -- `/newbot` |
| TELEGRAM_CHAT_ID | [@userinfobot](https://t.me/userinfobot) on Telegram |

**4. Test the pipeline**
```bash
bash run.sh --dry-run
```

If a watchlist prints and the script exits cleanly, everything is working.

**5. Start live trading**
```bash
sudo systemctl start nexus_trader
sudo systemctl status nexus_trader   # confirm it's running
sudo journalctl -u nexus_trader -f   # tail live logs
```

The scheduler wakes up automatically at 08:30 IST on trading days. No manual intervention needed.

---

## Run Modes

| Command | What it does |
|---------|-------------|
| `bash run.sh` | Live trading -- APScheduler runs Mon-Fri IST schedule |
| `bash run.sh --dry-run` | Pre-market pipeline on yesterday's data, then exits |
| `bash run.sh --backtest --start 2025-01-01 --end 2025-06-01` | Replay strategy on historical data |

---

## Schedule (IST, Mon-Fri only)

| Time | Agent | Action |
|------|-------|--------|
| 08:30 | I0, I1, I2, I3 | Global bias + gap scan + news + watchlist |
| 09:15 -- 15:15 | I4, I6 | Signal entry + exit monitoring (60s polls) |
| 15:35 | I9 | Claude Sonnet post-market review |

---

## Telegram Commands

Once running, message your bot:

| Command | Response |
|---------|----------|
| `/status` | Capital, daily P&L, trade count, halt status |
| `/positions` | All open positions with entry/SL/target |
| `/trades` | Today's closed trades with P&L |
| `/summary` | Last post-market review from AgentI9 |
| `/help` | Command list |

---

## Key Constraints

- Data: yfinance only (15-min delayed for NSE). No paid feeds.
- Long-only positions (v1). No short selling.
- Max 5 open positions, max 2 per sector.
- 1% risk per trade, 2% daily loss limit halts all trading.
- Entry window: 09:30 -- 14:00 IST. Force square-off at 15:15 IST.
- Min R:R ratio: 1.5

---

## Project Structure

```
nexus_trader/
├── main.py              -- Live trading entry point
├── backtest.py          -- Backtesting entry point
├── setup.sh             -- VM setup (run once after clone)
├── run.sh               -- Run wrapper
├── config.py            -- All settings
├── requirements.txt     -- Pinned dependencies
├── .env.example         -- API key template
├── agents/
│   ├── agent_i0.py      -- Global market bias (Gemini)
│   ├── agent_i1.py      -- Gap scanner
│   ├── agent_i2.py      -- News sentiment (Gemini)
│   ├── agent_i3.py      -- Strategy assignment + watchlist
│   ├── agent_i4.py      -- Intraday signal engine
│   ├── agent_i6.py      -- Position monitor + exits
│   └── agent_i9.py      -- Post-market review (Claude Sonnet)
├── data/
│   ├── universe.py      -- Nifty 100 stock list
│   ├── market_data.py   -- yfinance wrapper
│   └── indicators.py    -- VWAP, EMA, RSI, ATR, ORB
├── execution/
│   ├── scheduler.py     -- APScheduler (BackgroundScheduler)
│   ├── portfolio.py     -- SQLite paper portfolio
│   └── order_manager.py -- Position sizing + exit logic
├── utils/
│   ├── logger.py        -- colorlog structured logger
│   └── telegram_bot.py  -- Telegram command bot
├── tests/               -- pytest suite (89 tests)
└── logs/                -- Auto-created at runtime
```

---

## Updating the VM

```bash
cd nexus_trader
git pull
source venv/bin/activate
pip install -r requirements.txt --quiet
sudo systemctl restart nexus_trader
```
