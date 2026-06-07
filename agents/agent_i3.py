"""
AgentI3 -- Strategy Assignment + ATR Price Levels + Watchlist Builder.

Strategy rule table (priority order):
  BULLISH  + gap > 3.0%                   -> GAP_AND_GO
  BULLISH  + 2.0% < gap <= 3.0%           -> ORB_BREAKOUT
  NEUTRAL  + gap > 2.0%                   -> ORB_BREAKOUT
  BEARISH  + gap > 2.0%  (gap-UP stock)   -> SKIP (chasing longs against macro is risky)
  BEARISH  + gap < -2.0% (gap-DOWN stock) -> GAP_FILL (mean-reversion)
  1.5% <= abs(gap) <= 3.0% + gap-DOWN     -> GAP_FILL
  abs(gap) < 2.0%                         -> VWAP_RECLAIM
  Fallback                                -> VWAP_RECLAIM

GAP_FILL guard: target = prev_close is only valid when stock is gapping DOWN.
The R:R check already catches this, but we guard explicitly for clarity.
"""

import asyncio

import pytz

from agents.models import GapCandidate, MarketBias, WatchlistEntry
from config import config
from data.market_data import MarketDataFetcher
from utils.logger import setup_logger

logger = setup_logger(__name__)
from utils.decision_logger import dlog
IST = pytz.timezone("Asia/Kolkata")

fetcher = MarketDataFetcher()

# Sentinel: _assign_strategy returns this to signal the candidate should be dropped
_SKIP = "__SKIP__"


async def run(
    candidates: list[GapCandidate],
    bias: MarketBias,
    watchlist_ready: asyncio.Event | None = None,
) -> list[WatchlistEntry]:
    """Main entry point. Never raises."""
    entries = await asyncio.to_thread(_build_watchlist, candidates, bias)
    logger.info("AgentI3 watchlist: %d entries", len(entries))
    if watchlist_ready is not None:
        watchlist_ready.set()
    return entries


def _build_watchlist(
    candidates: list[GapCandidate], bias: MarketBias
) -> list[WatchlistEntry]:
    results: list[WatchlistEntry] = []

    for candidate in candidates:
        try:
            atr = fetcher.get_atr(candidate.symbol)
            if atr is None or atr <= 0:
                logger.warning("%s: ATR unavailable -- skipping", candidate.symbol)
                continue

            strategy = _assign_strategy(candidate, bias)

            if strategy == _SKIP:
                logger.info(
                    "%s: skipped (bias=%s, gap_pct=%.2f%%)",
                    candidate.symbol, bias.bias, candidate.gap_pct,
                )
                continue

            levels = _compute_levels(candidate, strategy, atr)
            entry_trigger = levels["entry_trigger"]
            stop_loss = levels["stop_loss"]
            target = levels["target"]

            denom = entry_trigger - stop_loss
            if denom <= 0:
                logger.debug(
                    "%s: stop >= entry (denom=%.2f) -- skipped", candidate.symbol, denom
                )
                continue

            # GAP_FILL direction guard: target must be above entry
            if strategy == "GAP_FILL" and target <= entry_trigger:
                logger.debug(
                    "%s: GAP_FILL target (%.2f) <= entry (%.2f) -- negative R:R, skipped",
                    candidate.symbol, target, entry_trigger,
                )
                continue

            rr_ratio = (target - entry_trigger) / denom
            if rr_ratio < config.MIN_RR_RATIO:
                logger.debug(
                    "%s: R:R %.2f < %.2f -- skipped",
                    candidate.symbol, rr_ratio, config.MIN_RR_RATIO,
                )
                continue

            entry_obj = WatchlistEntry(
                    symbol=candidate.symbol,
                    sector=candidate.sector,
                    gap_pct=candidate.gap_pct,
                    gap_score=candidate.gap_score,
                    strategy=strategy,
                    entry_trigger=entry_trigger,
                    stop_loss=stop_loss,
                    target=target,
                    rr_ratio=round(rr_ratio, 2),
                    catalyst_type=candidate.catalyst_type,
                    atr=atr,
                )
            results.append(entry_obj)
            dlog.watchlist_entry(
                symbol=candidate.symbol,
                sector=candidate.sector or "Unknown",
                strategy=strategy,
                gap_pct=candidate.gap_pct,
                bias=bias.bias,
                entry_trigger=entry_trigger,
                stop_loss=stop_loss,
                target=target,
                rr_ratio=round(rr_ratio, 2),
                atr=atr,
                reasoning=f"gap={candidate.gap_pct:+.2f}%, bias={bias.bias}, abs_gap={abs(candidate.gap_pct):.2f}%",
            )
        except Exception as exc:
            logger.warning("%s: AgentI3 error -- %s", candidate.symbol, exc)
            continue

    results.sort(key=lambda x: x.gap_score, reverse=True)
    return results[: config.MAX_WATCHLIST_SIZE]


def _assign_strategy(candidate: GapCandidate, bias: MarketBias) -> str:
    """
    Deterministic rule table. Returns _SKIP to exclude a candidate entirely.

    gap_pct > 0: stock gapping UP today
    gap_pct < 0: stock gapping DOWN today
    """
    abs_gap = abs(candidate.gap_pct)
    gap_is_up = candidate.gap_pct > 0

    if bias.bias == "BULLISH":
        if abs_gap > 3.0:
            return "GAP_AND_GO"
        if abs_gap > 2.0:
            return "ORB_BREAKOUT"
        if 1.5 <= abs_gap <= 3.0 and not gap_is_up:
            return "GAP_FILL"
        return "VWAP_RECLAIM"

    if bias.bias == "NEUTRAL":
        if abs_gap > 2.0:
            return "ORB_BREAKOUT"
        if 1.5 <= abs_gap <= 3.0 and not gap_is_up:
            return "GAP_FILL"
        return "VWAP_RECLAIM"

    if bias.bias == "BEARISH":
        # Gap-up longs against bearish market -- too risky, skip
        if gap_is_up and abs_gap > 2.0:
            return _SKIP
        if not gap_is_up and abs_gap >= 1.5:
            return "GAP_FILL"
        return "VWAP_RECLAIM"

    # Unknown bias -- conservative fallback
    return "VWAP_RECLAIM"


def _compute_levels(
    candidate: GapCandidate, strategy: str, atr: float
) -> dict[str, float]:
    """ATR-based price level formulas. All values rounded to 2 dp."""
    p = candidate.premarket_price
    pc = candidate.prev_close

    if strategy == "GAP_AND_GO":
        entry_trigger = round(p * 1.002, 2)
        stop_loss = round(entry_trigger - 1.5 * atr, 2)
        target = round(entry_trigger + 2.25 * atr, 2)

    elif strategy == "GAP_FILL":
        # Gap-down stock: price rallies back toward prev_close
        entry_trigger = round(p * 1.001, 2)
        stop_loss = round(entry_trigger - 1.0 * atr, 2)
        target = round(pc, 2)

    elif strategy == "ORB_BREAKOUT":
        # Placeholder entry_trigger -- overridden by ORB logic at 09:30
        entry_trigger = round(p * 1.005, 2)
        stop_loss = round(pc - 0.5 * atr, 2)
        target = round(entry_trigger + 2.0 * atr, 2)

    else:  # VWAP_RECLAIM
        entry_trigger = round(p * 1.001, 2)
        stop_loss = round(entry_trigger - 1.0 * atr, 2)
        target = round(entry_trigger + 1.5 * atr, 2)

    return {"entry_trigger": entry_trigger, "stop_loss": stop_loss, "target": target}
