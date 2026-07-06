import json
import logging
import os
from datetime import date as _date
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# AgentI9 self-tuning. After each session AgentI9 writes its validated parameter
# suggestions here (repo root); Config._apply_overrides() loads them at the next
# startup and RE-CLAMPS every value, so a stale/corrupt file can never widen risk
# past the hard caps. Only risk-reducing params are honoured.
_OVERRIDE_PATH = os.path.join(os.path.dirname(__file__), "param_overrides.json")


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
        self.MAX_POSITION_PCT     = 0.40   # 40% of equity notional per position. With
                                           # MAX_OPEN_POSITIONS=3 and MIS_LEVERAGE=1.2 below,
                                           # max deployment = 3*40% = 120% gross (1.2x). Per-trade
                                           # risk = 40% * 1.5% stop = 0.6%; 3 simultaneous stops =
                                           # 1.8% (well under the 4% daily halt).
        self.DAILY_LOSS_LIMIT_PCT = 0.04   # halt if daily P&L < -4%

        # Intraday leverage (simulated MIS buying power). 1-yr walk-forward
        # (2025-06..2026-06, commit-time backtest) showed leverage only SCALES
        # the edge -- it does not improve it: 2x = +12.7%/maxDD 6.1%/Sharpe 0.81,
        # 1.2x = +11.1%/maxDD 4.3%/Sharpe 0.87, 1x = +6.6%/maxDD 2.9%/Sharpe 0.87.
        # 1.2x chosen: ~all of 2x's return at better risk-adjusted return and
        # clear of the 4% halt. Buying power = CAPITAL * MIS_LEVERAGE = 120k =
        # exactly 3 x 40% positions. MIS_LEVERAGE=1.0 restores pure cash gating.
        self.MIS_LEVERAGE         = 1.2

        # Position limits
        self.MAX_OPEN_POSITIONS      = 3
        self.MAX_TRADES_PER_DAY      = 15
        self.MAX_POSITIONS_PER_SECTOR = 2  # sector concentration guard

        # Defensive entry guards (2026-07-02, after 4 same-sector SL_HITs on Jul 1)
        self.SECTOR_STOPOUT_LIMIT   = 2   # SL_HITs in one sector today -> block new entries in that sector
        self.CONSECUTIVE_STOP_HALT  = 3   # last N closed trades all SL_HIT -> no new entries today

        # Multi-day loss brakes (2026-07-06, after 4 straight red sessions Jul 1-6).
        # Percentages are of starting CAPITAL, not current equity.
        self.BIG_LOSS_COOLDOWN_PCT      = 0.02   # prev session net <= -2% -> no entries today
        self.ROLLING_LOSS_LOOKBACK_DAYS = 5      # calendar-day window for the rolling brake
        self.ROLLING_LOSS_HALT_PCT      = 0.025  # window net <= -2.5% -> no entries today

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

        # Apply AgentI9's persisted overrides last, on top of the defaults above.
        self._apply_overrides()

        self._warn_if_calendar_stale()

    def _apply_overrides(self) -> None:
        """Load AgentI9's param_overrides.json and apply re-clamped values.

        Auto-tuning may only TIGHTEN risk: each param is clamped so the file can
        never raise risk above the validated defaults. Missing/unreadable file is
        a no-op. RISK_PER_TRADE_PCT is stored in percent form (e.g. 1.5 == 1.5%).
        """
        try:
            with open(_OVERRIDE_PATH, encoding="utf-8") as fh:
                ov = json.load(fh)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("param_overrides.json unreadable (%s) -- ignoring", e)
            return
        if not isinstance(ov, dict):
            return

        applied: dict = {}
        if "RISK_PER_TRADE_PCT" in ov:
            try:
                v = max(0.005, min(float(ov["RISK_PER_TRADE_PCT"]) / 100.0, 0.02))
                self.RISK_PER_TRADE_PCT = v
                applied["RISK_PER_TRADE_PCT"] = v
            except (TypeError, ValueError):
                pass
        if "MIN_RISK_REWARD" in ov:
            try:
                v = max(1.5, float(ov["MIN_RISK_REWARD"]))
                self.MIN_RISK_REWARD = v
                applied["MIN_RISK_REWARD"] = v
            except (TypeError, ValueError):
                pass
        if "MAX_OPEN_POSITIONS" in ov:
            try:
                v = max(1, min(int(ov["MAX_OPEN_POSITIONS"]), self.MAX_OPEN_POSITIONS))
                self.MAX_OPEN_POSITIONS = v
                applied["MAX_OPEN_POSITIONS"] = v
            except (TypeError, ValueError):
                pass
        if applied:
            logger.info("Applied AgentI9 parameter overrides: %s", applied)

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
