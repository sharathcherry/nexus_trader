import logging
import os
from datetime import date as _date
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    def __init__(self):
        # Required API keys -- crash hard at startup if missing
        self.GEMINI_API_KEY  = self._require("GEMINI_API_KEY")
        self.GROQ_API_KEY    = self._require("GROQ_API_KEY")

        # Optional -- Telegram notifier auto-disables when absent/placeholder
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

        # yfinance fallback toggle. Yahoo IP-blocks the production VM, so every
        # yfinance call there returns empty after a wasted rate-limit sleep,
        # spamming logs and adding minutes of latency to the scan. Set
        # YFINANCE_ENABLED=false on the VM to fast-fail the fallback; leave the
        # default (true) for local dev where yfinance still works.
        self.YFINANCE_ENABLED = os.getenv("YFINANCE_ENABLED", "true").strip().lower() != "false"

        # Capital and risk
        self.CAPITAL              = 100_000
        self.RISK_PER_TRADE_PCT   = 0.02   # 2% risk per trade (aggressive; gap-fill is 72-80% win)
        self.MAX_POSITION_PCT     = 0.40   # 40% of equity notional per position. With MIS_LEVERAGE
                                           # below, MAX_OPEN_POSITIONS * MAX_POSITION_PCT = 5*40% =
                                           # 200% notional -- exactly the deployment the validated
                                           # backtest assumed (it sized 5 positions at 40% with no
                                           # cash gate). Per-trade risk = 40% * 1.5% stop = 0.6% of
                                           # equity; 5 simultaneous stops = 3% (= backtest maxDD).
        self.DAILY_LOSS_LIMIT_PCT = 0.04   # halt if daily P&L < -4% (sits just above the 3% maxDD)

        # Intraday leverage. Real NSE MIS gives ~5x; the validated gap-fill
        # backtest implicitly assumed ~2x (it held up to 5 positions at 40%
        # notional = 200% gross with no cash constraint). 2.0 reproduces that
        # profile. The paper portfolio is otherwise cash-funded (1x); this only
        # raises buying power so the 5-slot design is actually reachable.
        # MIS_LEVERAGE = 1.0 restores the pure cash-gated behaviour.
        self.MIS_LEVERAGE         = 2.0

        # Position limits
        self.MAX_OPEN_POSITIONS      = 5
        self.MAX_TRADES_PER_DAY      = 15
        self.MAX_POSITIONS_PER_SECTOR = 2  # sector concentration guard

        # Entry/exit R:R
        self.MIN_RISK_REWARD = 1.5

        # Gap filter
        self.GAP_MIN_PCT      = 1.5
        self.GAP_MAX_PCT      = 8.0
        self.MIN_PREV_VOLUME  = 500_000
        self.MIN_PRICE        = 50
        self.MAX_PRICE        = 5_000

        # Volume ratio filter (applied in AgentI1)
        self.MIN_VOLUME_RATIO = 1.2        # current vol >= 1.2x 20-period avg

        # Entry window (IST)
        self.ENTRY_CUTOFF_HOUR   = 14      # no new entries after 14:00
        self.ENTRY_START_HOUR    = 9
        self.ENTRY_START_MINUTE  = 30      # no entries before 09:30

        # ORB window
        self.ORB_MINUTES = 15

        # Watchlist sizing
        self.MAX_GAP_CANDIDATES  = 20
        self.MAX_WATCHLIST_SIZE  = 10

        self._warn_if_calendar_stale()

    # NSE holiday calendars -- update each year
    _NSE_HOLIDAYS_2026: frozenset = frozenset({
        _date(2026, 1, 26), _date(2026, 3, 25), _date(2026, 4, 2),
        _date(2026, 4, 10), _date(2026, 4, 14), _date(2026, 5, 1),
        _date(2026, 8, 15), _date(2026, 10, 2), _date(2026, 10, 22),
        _date(2026, 11, 4), _date(2026, 11, 5), _date(2026, 11, 25),
        _date(2026, 12, 25),
    })
    _NSE_HOLIDAYS_2027: frozenset = frozenset()

    @property
    def _current_holidays(self) -> frozenset:
        year = _date.today().year
        if year == 2026:
            return self._NSE_HOLIDAYS_2026
        if year == 2027:
            return self._NSE_HOLIDAYS_2027
        logger.warning("No holiday calendar for year %d -- using 2026 as fallback", year)
        return self._NSE_HOLIDAYS_2026

    def _warn_if_calendar_stale(self) -> None:
        year = _date.today().year
        if year == 2027 and not self._NSE_HOLIDAYS_2027:
            logger.warning(
                "NSE holiday calendar for 2027 is empty. "
                "Update Config._NSE_HOLIDAYS_2027 with the official NSE holiday list."
            )
        elif year > 2027:
            logger.warning(
                "Running in %d but no holiday calendar configured beyond 2027. "
                "Update config.py with the official NSE holiday list for %d.",
                year, year,
            )

    def is_trading_day(self, dt: _date | None = None) -> bool:
        if dt is None:
            dt = _date.today()
        if dt.weekday() >= 5:
            return False
        return dt not in self._current_holidays

    @property
    def MIN_RR_RATIO(self) -> float:
        return self.MIN_RISK_REWARD

    @staticmethod
    def _require(key: str) -> str:
        val = os.getenv(key, "").strip()
        if not val or val.lower().startswith("your_") or "placeholder" in val.lower():
            raise ValueError(
                f"Required environment variable '{key}' is missing or contains placeholder value '{val}'. "
                f"Required env var '{key}' is missing or has a placeholder value. "
                "Set it in your .env file."
            )
        return val


config = Config()
