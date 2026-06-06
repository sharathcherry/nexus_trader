import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        # API keys — crash hard if any are missing
        self.GEMINI_API_KEY = self._require("GEMINI_API_KEY")
        self.ANTHROPIC_API_KEY = self._require("ANTHROPIC_API_KEY")
        self.TELEGRAM_BOT_TOKEN = self._require("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID = self._require("TELEGRAM_CHAT_ID")

        # Capital and risk
        self.CAPITAL = 100_000
        self.RISK_PER_TRADE_PCT = 0.01        # 1% risk per trade
        self.DAILY_LOSS_LIMIT_PCT = 0.02      # halt if daily P&L < -2%

        # Position limits
        self.MAX_OPEN_POSITIONS = 5
        self.MAX_TRADES_PER_DAY = 15

        # Entry/exit R:R
        self.MIN_RISK_REWARD = 1.5
        self.MIN_RR_RATIO = 1.5               # alias used by Phase 4a agents

        # Gap filter
        self.GAP_MIN_PCT = 1.5
        self.GAP_MAX_PCT = 8.0
        self.MIN_PREV_VOLUME = 500_000
        self.MIN_PRICE = 50
        self.MAX_PRICE = 5_000

        # Entry window (IST)
        self.ENTRY_CUTOFF_HOUR = 14           # no new entries after 14:00
        self.ENTRY_START_HOUR = 9
        self.ENTRY_START_MINUTE = 30          # no entries before 09:30

        # ORB window
        self.ORB_MINUTES = 15

        # Watchlist sizing
        self.MAX_GAP_CANDIDATES = 20
        self.MAX_WATCHLIST_SIZE = 10

    def _require(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise ValueError(
                f"Missing required environment variable: {key}\n"
                f"Copy .env.example to .env and set {key}"
            )
        return value


config = Config()
