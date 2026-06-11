"""
AgentI1 -- Gap Scanner.

Scans the Nifty 100 universe for gap candidates each pre-market session.
Filters applied (in order):
  1. gap_pct within [GAP_MIN_PCT, GAP_MAX_PCT]
  2. prev_volume >= MIN_PREV_VOLUME
  3. premarket_price within [MIN_PRICE, MAX_PRICE]
  4. volume_ratio >= MIN_VOLUME_RATIO (current session volume vs 20-bar avg)
     -- filters out low-conviction gaps where today's volume hasn't confirmed yet
Returns top MAX_GAP_CANDIDATES by gap_score.
"""

import asyncio

import pytz

from agents.models import GapCandidate, MarketBias
from config import config
from data.indicators import Indicators
from data.market_data import MarketDataFetcher
from data.universe import get_nse_universe as get_universe
from utils.logger import setup_logger


logger = setup_logger(__name__)
IST = pytz.timezone("Asia/Kolkata")
fetcher = MarketDataFetcher()


async def run(price_source: str = "live") -> list[GapCandidate]:
    return await asyncio.to_thread(_scan_universe, price_source=price_source)


def _scan_universe(price_source: str = "live") -> list[GapCandidate]:
    """
    Scan the universe for gap candidates.

    price_source:
      "live"    -- (default) compute the opening gap from the first live 5-min
                   candle open vs prev_close and apply the Filter-4 volume
                   conviction check. Preserves the historical behaviour.
      "preopen" -- source premarket_price + prev_close from a single batch
                   get_preopen_snapshot() call (Upstox pre-open IEP). Filter-4
                   is skipped (no intraday bars exist yet). Returns [] if the
                   snapshot is empty so the caller degrades to a 09:15-only scan.
    """
    candidates: list[GapCandidate] = []
    universe = get_universe()

    # Pre-open path: one batch snapshot up front; degrade if empty.
    snapshot: dict[str, dict] = {}
    if price_source == "preopen":
        symbols = [s.get("symbol") for s in universe if s.get("symbol")]
        snapshot = fetcher.get_preopen_snapshot(symbols)
        if not snapshot:
            logger.warning("Pre-open snapshot empty -- skipping provisional scan")
            return []

    for stock in universe:
        symbol = stock.get("symbol")
        sector = stock.get("sector", "UNKNOWN")

        if not symbol:
            continue

        try:
            if price_source == "preopen":
                snap = snapshot.get(symbol)
                if snap is None:
                    continue  # symbol absent from snapshot
                premarket_price = snap.get("price")
                prev_close = snap.get("prev_close")
                if prev_close is None:
                    prev_close = fetcher.get_previous_close(symbol)
                if premarket_price is None or prev_close is None:
                    continue
            else:
                prev_close = fetcher.get_previous_close(symbol)
                if prev_close is None:
                    continue

            hist = fetcher.get_historical_data(symbol, period="5d")
            if len(hist) < 2:
                continue

            prev_volume = hist["Volume"].iloc[-2]

            intraday_df = None
            if price_source == "live":
                # True opening gap from the first live 5-min candle open.
                intraday_df = fetcher.get_intraday_candles(symbol)
                if intraday_df is not None and not intraday_df.empty:
                    premarket_price = float(intraday_df["Open"].iloc[0])
                else:
                    premarket_price = fetcher.get_premarket_price(symbol)
                if premarket_price is None:
                    continue

            gap_pct = (premarket_price - prev_close) / prev_close * 100

            # --- Filter 1: gap size ---
            if abs(gap_pct) < config.GAP_MIN_PCT or abs(gap_pct) > config.GAP_MAX_PCT:
                continue

            # --- Filter 2: previous day volume ---
            if prev_volume < config.MIN_PREV_VOLUME:
                continue

            # --- Filter 3: price band ---
            if premarket_price < config.MIN_PRICE or premarket_price > config.MAX_PRICE:
                continue

            # --- Filter 4: today's volume ratio (conviction filter) ---
            # Live path only -- the pre-open path has no intraday bars yet, so
            # it is skipped (mirrors the prior vol_ratio==0 "allow through").
            if price_source == "live" and intraday_df is not None and not intraday_df.empty:
                vol_ratio = Indicators.volume_ratio(intraday_df, lookback=20)
                if vol_ratio > 0 and vol_ratio < config.MIN_VOLUME_RATIO:
                    logger.debug(
                        "%s: volume_ratio=%.2f < %.2f -- low conviction, skipped",
                        symbol, vol_ratio, config.MIN_VOLUME_RATIO,
                    )
                    continue
                # vol_ratio == 0 means insufficient bars (pre-market) -> allow through

            # Score: larger gap x higher volume -> prioritise
            gap_score = abs(gap_pct) * min(prev_volume / 500_000, 3.0)

            candidates.append(
                GapCandidate(
                    symbol=symbol,
                    sector=sector,
                    prev_close=prev_close,
                    premarket_price=premarket_price,
                    gap_pct=gap_pct,
                    prev_volume=int(prev_volume),
                    gap_score=gap_score,
                )
            )
        except Exception as exc:
            logger.warning("AgentI1 error scanning %s: %s", symbol, exc)
            continue

    if len(candidates) < 3:
        logger.warning("Fewer than 3 gap candidates found -- NO_TRADE_DAY")
        return []

    candidates.sort(key=lambda candidate: candidate.gap_score, reverse=True)
    result = candidates[: config.MAX_GAP_CANDIDATES]
    logger.info(
        "AgentI1 found %s candidates -> top %s selected",
        len(candidates),
        len(result),
    )
    return result


def apply_direction_filter(
    candidates: list[GapCandidate], bias: MarketBias
) -> list[GapCandidate]:
    """
    Filter candidates based on market bias direction.

    BULLISH: only gap-UP stocks (momentum with the market)
    BEARISH: only gap-DOWN stocks (mean-reversion plays, not chasing longs)
    NEUTRAL: all candidates (both directions acceptable)
    """
    if bias.bias == "BULLISH":
        filtered = [c for c in candidates if c.gap_pct > 0]
    elif bias.bias == "BEARISH":
        # On bearish days allow gap-DOWN candidates only (GAP_FILL plays).
        # Gap-up stocks on bearish days are handled by AgentI3 (_SKIP sentinel).
        filtered = [c for c in candidates if c.gap_pct < 0]
    else:
        filtered = candidates

    logger.info(
        "Direction filter [%s]: %s -> %s candidates",
        bias.bias,
        len(candidates),
        len(filtered),
    )
    return filtered
