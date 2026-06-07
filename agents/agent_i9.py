"""
agents/agent_i9.py -- AgentI9: Post-Market Reviewer (Groq / llama-3.3-70b-versatile)

Reads today's closed trades + 20-day rolling stats from the portfolio DB,
calls Groq with JSON mode to produce a structured DailyReview, validates
parameter suggestions, writes JSON output to logs/performance/, and logs
the full AI reasoning to logs/decisions/.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import pytz

IST = pytz.timezone("Asia/Kolkata")

from groq import Groq, APIConnectionError, APITimeoutError, RateLimitError, APIStatusError
from pydantic import BaseModel, ValidationError
from tabulate import tabulate

from config import config
from utils.decision_logger import dlog
from utils.logger import setup_logger
from utils.telegram import notifier

logger = setup_logger(__name__)

PERF_DIR = Path("logs/performance")
DB_PATH  = Path("execution/portfolio.db")

MODEL      = "llama-3.3-70b-versatile"
MAX_TOKENS = 2048
TOKEN_CAP  = 8_000           # Groq context is generous; stay conservative
CHARS_PER_TOKEN = 4

SYSTEM_PROMPT = """You are a quantitative trading analyst reviewing an NSE India intraday paper trading session.
Identify what worked, what failed, and suggest conservative parameter adjustments.

IMPORTANT:
- Respond with ONLY a valid JSON object matching the schema below -- no prose, no markdown
- session_verdict must be exactly "PROFITABLE", "BREAKEVEN", or "LOSS"
- parameter_adjustments current_value for RISK_PER_TRADE_PCT is in percentage form (1.0 means 1%)
- tomorrow_watch contains up to 5 NSE symbol strings (e.g. "RELIANCE.NS")
- Be conservative -- do NOT suggest raising position limits or risk per trade significantly
- NSE data is 15-minute delayed from live market

Schema:
{
  "session_verdict": "PROFITABLE|BREAKEVEN|LOSS",
  "winning_strategies": ["strategy name", ...],
  "underperforming_strategies": ["strategy name", ...],
  "parameter_adjustments": [
    {"param_name": "string", "current_value": 0.0, "suggested_value": 0.0, "reason": "string"}
  ],
  "tomorrow_watch": ["NSE.NS", ...],
  "summary": "one paragraph summary of the session"
}"""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ParameterChange(BaseModel):
    param_name:      str
    current_value:   float
    suggested_value: float
    reason:          str


class DailyReview(BaseModel):
    session_verdict:             str
    winning_strategies:          list[str]
    underperforming_strategies:  list[str]
    parameter_adjustments:       list[ParameterChange]
    tomorrow_watch:              list[str]
    summary:                     str


# ---------------------------------------------------------------------------
# AgentI9
# ---------------------------------------------------------------------------

class AgentI9:
    """Post-market review agent -- calls Groq llama-3.3-70b to analyse the day."""

    def __init__(self, portfolio) -> None:
        self.portfolio = portfolio
        self._client   = Groq(api_key=config.GROQ_API_KEY)
        PERF_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // CHARS_PER_TOKEN

    def _get_rolling_stats(self, days: int = 20) -> dict:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cutoff_date = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
                cur.execute(
                    """
                    SELECT strategy,
                           COUNT(*) AS trade_count,
                           AVG(net_pnl) AS avg_net_pnl,
                           SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate
                    FROM trades
                    WHERE DATE(exit_time) >= :cutoff_date
                    GROUP BY strategy
                    """,
                    {"cutoff_date": cutoff_date},
                )
                strategy_rows = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    """
                    SELECT COUNT(*) AS total_trades,
                           SUM(net_pnl) AS total_net_pnl,
                           SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate_overall
                    FROM trades
                    WHERE DATE(exit_time) >= :cutoff_date
                    """,
                    {"cutoff_date": cutoff_date},
                )
                totals_row = cur.fetchone()
                totals = dict(totals_row) if totals_row else {}
            finally:
                conn.close()
            return {"strategy_breakdown": strategy_rows, "totals": totals}
        except sqlite3.OperationalError as exc:
            logger.error("Rolling stats DB error: %s", exc)
            return {"strategy_breakdown": [], "totals": {}}

    def _build_prompt(
        self,
        today_trades: list[dict],
        rolling_stats: dict,
        omit_times: bool = False,
    ) -> str:
        sections: list[str] = []

        sections.append(
            "=== CURRENT CONFIG ===\n"
            f"MAX_OPEN_POSITIONS : {config.MAX_OPEN_POSITIONS}\n"
            f"MIN_RISK_REWARD    : {config.MIN_RISK_REWARD}\n"
            f"RISK_PER_TRADE_PCT : {config.RISK_PER_TRADE_PCT * 100:.1f}%\n"
        )

        if today_trades:
            cols = (
                ["symbol", "strategy", "entry_price", "exit_price",
                 "gross_pnl", "net_pnl", "exit_reason"]
                if omit_times else
                ["symbol", "strategy", "entry_price", "exit_price",
                 "entry_time", "exit_time", "gross_pnl", "net_pnl", "exit_reason"]
            )
            rows = [[t.get(c) for c in cols] for t in today_trades]
            sections.append(
                f"=== TODAY'S TRADES ===\n"
                f"{tabulate(rows, headers=cols, tablefmt='grid', floatfmt='.2f')}\n"
            )
        else:
            sections.append("=== TODAY'S TRADES ===\nNo trades today.\n")

        strategy_breakdown = rolling_stats.get("strategy_breakdown", [])
        totals             = rolling_stats.get("totals", {})

        if strategy_breakdown:
            strat_cols = ["strategy", "trade_count", "avg_net_pnl", "win_rate"]
            strat_rows = [[r.get(c) for c in strat_cols] for r in strategy_breakdown]
            sections.append(
                f"=== 20-DAY ROLLING STATS (by strategy) ===\n"
                f"{tabulate(strat_rows, headers=strat_cols, tablefmt='grid', floatfmt='.4f')}\n"
            )
        else:
            sections.append("=== 20-DAY ROLLING STATS ===\nNo rolling data yet.\n")

        total_trades     = totals.get('total_trades') or 0
        total_net_pnl    = totals.get('total_net_pnl') or 0.0
        win_rate_overall = totals.get('win_rate_overall') or 0.0
        sections.append(
            f"Overall (20-day):\n"
            f"  total_trades    : {total_trades}\n"
            f"  total_net_pnl   : {float(total_net_pnl):.2f}\n"
            f"  win_rate_overall: {float(win_rate_overall):.4f}\n"
        )
        sections.append(
            "=== DATA NOTE ===\n"
            "yfinance NSE data is 15-minute delayed from live market.\n"
        )
        return "\n".join(sections)

    def _validate_parameter_adjustments(
        self, adjustments: list[ParameterChange]
    ) -> list[ParameterChange]:
        valid: list[ParameterChange] = []
        for adj in adjustments:
            if adj.param_name == "MAX_OPEN_POSITIONS" and adj.suggested_value > config.MAX_OPEN_POSITIONS:
                logger.warning("MAX_OPEN_POSITIONS: suggestion raises limit -- rejected")
                continue
            if adj.param_name == "MIN_RISK_REWARD" and adj.suggested_value < 1.5:
                logger.warning("MIN_RISK_REWARD: suggestion below 1.5 -- rejected")
                continue
            if adj.param_name == "RISK_PER_TRADE_PCT" and adj.suggested_value > 1.5:
                logger.warning("RISK_PER_TRADE_PCT: suggestion above 1.5%% cap -- rejected")
                continue
            valid.append(adj)
        return valid

    def _print_summary(
        self,
        review: DailyReview | None,
        state: str,
        today_str: str,
        today_trades: list[dict],
    ) -> None:
        if state == "success" and review:
            rows = [
                [t.get("symbol"), t.get("strategy"), t.get("entry_price"),
                 t.get("exit_price"), t.get("net_pnl"), t.get("exit_reason")]
                for t in today_trades
            ]
            print(tabulate(
                rows,
                headers=["Symbol", "Strategy", "Entry", "Exit", "Net P&L", "Reason"],
                tablefmt="grid",
                floatfmt=".2f",
            ))
            print(f"\nVerdict : {review.session_verdict}")
            print(f"Summary : {review.summary}")
        elif state == "partial":
            print(f"[AgentI9] Partial review -- raw saved to review_partial_{today_str}.json")
        else:
            print(f"[AgentI9] Review failed -- see review_failed_{today_str}.json")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> DailyReview | None:
        today_str    = date.today().strftime("%Y%m%d")
        _state       = "failed"
        _fail_detail = ""
        review: DailyReview | None = None
        raw_response = ""
        tokens_used  = 0

        # Step 1 -- Gather data
        report       = self.portfolio.get_daily_report()
        today_trades = report.get("trades", []) if isinstance(report, dict) else (report or [])
        rolling_stats = self._get_rolling_stats(days=20)

        # Step 2 -- Build prompt with token budget
        prompt = self._build_prompt(today_trades, rolling_stats)
        for days in [15, 10]:
            if self._estimate_tokens(prompt) <= TOKEN_CAP:
                break
            rolling_stats = self._get_rolling_stats(days=days)
            prompt = self._build_prompt(today_trades, rolling_stats)
            logger.warning("Prompt trimmed to %d-day window", days)
        if self._estimate_tokens(prompt) > TOKEN_CAP:
            prompt = self._build_prompt(today_trades, rolling_stats, omit_times=True)
            logger.warning("Dropped timestamps to fit token budget")

        logger.info("AgentI9 prompt ~%d tokens", self._estimate_tokens(prompt))

        # Step 3 -- Call Groq
        try:
            response = self._client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=MAX_TOKENS,
                temperature=0.2,       # low temp for consistent structured output
            )
            raw_response = response.choices[0].message.content or ""
            tokens_used  = response.usage.total_tokens if response.usage else 0
            logger.info("Groq response received -- %d tokens used", tokens_used)
            _state = "pending_parse"

        except (APIConnectionError, APITimeoutError) as exc:
            logger.error("Groq connection/timeout error: %s", exc)
            _fail_detail = str(exc)
        except RateLimitError as exc:
            logger.error("Groq rate limit hit: %s", exc)
            _fail_detail = str(exc)
        except APIStatusError as exc:
            logger.error("Groq API status error %s: %s", exc.status_code, exc)
            _fail_detail = str(exc)

        # Step 4 -- Parse
        if _state == "pending_parse":
            try:
                data   = json.loads(raw_response)
                review = DailyReview(**data)
                review.parameter_adjustments = self._validate_parameter_adjustments(
                    review.parameter_adjustments
                )
                _state = "success"
            except json.JSONDecodeError as exc:
                logger.error("JSON parse failed: %s", exc)
                _state = "partial"
            except ValidationError as exc:
                logger.error("Schema validation failed: %s", exc)
                _state = "partial"

        # Step 5 -- Write output files
        if _state == "success" and review:
            (PERF_DIR / f"review_{today_str}.json").write_text(
                review.model_dump_json(indent=2), encoding="utf-8"
            )
            # SQLite persistence
            try:
                self.portfolio.save_daily_review(
                    review_date=today_str,
                    verdict=review.session_verdict,
                    winning_strategies=review.winning_strategies,
                    underperforming_strategies=review.underperforming_strategies,
                    parameter_adjustments=[a.model_dump() for a in review.parameter_adjustments],
                    tomorrow_watch=review.tomorrow_watch,
                    summary=review.summary,
                )
            except Exception as e:
                logger.error("Failed to save daily review to database: %s", e)

            # Full decision audit log
            dlog.review_complete(
                verdict=review.session_verdict,
                summary=review.summary,
                winning_strategies=review.winning_strategies,
                underperforming_strategies=review.underperforming_strategies,
                parameter_adjustments=[a.model_dump() for a in review.parameter_adjustments],
                tomorrow_watch=review.tomorrow_watch,
                raw_ai_response=raw_response,
                model_used=MODEL,
                tokens_used=tokens_used,
            )
        elif _state == "partial":
            (PERF_DIR / f"review_partial_{today_str}.json").write_text(
                raw_response, encoding="utf-8"
            )
        else:
            (PERF_DIR / f"review_failed_{today_str}.json").write_text(
                json.dumps({"error": "api_failure", "date": today_str, "detail": _fail_detail}),
                encoding="utf-8",
            )

        # Step 6 -- Print + notify
        self._print_summary(review, _state, today_str, today_trades)
        if _state == "success" and review:
            try:
                notifier.send_review(
                    verdict=review.session_verdict,
                    summary=review.summary[:400],
                )
            except Exception:
                pass  # Telegram is optional

        return review if _state == "success" else None
