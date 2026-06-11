"""
AgentI1 -- Gap Scanner.

Scans the Nifty 500 universe for gap candidates each pre-market session.

Performance architecture (T2 — 335-symbol universe on a 1-vCPU VM):
  pre-open path:
    1. ONE batch Upstox get_preopen_snapshot() call → gap for all symbols.
    2. Apply gap-size (F1) + price-band (F3) filters → shortlist top-N.
    3. Per-symbol enrichment (prev_volume, ATR, volume_ratio) ONLY on
       the shortlist (~20 symbols).  This keeps the expensive work small.
    4. Apply volume filter (F2) and volume-ratio filter (F4) on shortlist.

  live path (post-open, 09:15+ candles available):
    Same per-symbol fetch but universe is already the shortlist from
    pre-open stage; volume_ratio can be computed from intraday bars.

Filters applied (in order):
  1. gap_pct within [GAP_MIN_PCT, GAP_MAX_PCT]
  2. prev_volume >= MIN_PREV_VOLUME
  3. premarket_price within [MIN_PRICE, MAX_PRICE]
  4. volume_ratio >= MIN_VOLUME_RATIO (live path only)
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

# Maximum number of shortlisted symbols to enrich in the pre-open pass.
# Chosen so enrichment fits comfortably within the pre-market window while
# leaving headroom for the ATR / historical fetch.
_PREOPEN_SHORTLIST_SIZE = 40


async def run(price_source: str = "live") -> list[GapCandidate]:
    return await asyncio.to_thread(_scan_universe, price_source=price_source)


def _scan_universe(price_source: str = "live") -> list[GapCandidate]:
    """
    Scan the universe for gap candidates.

    price_source:
      "live"    -- (default) compute the opening gap from the first live 5-min
                   candle open vs prev_close and apply the Filter-4 volume
                   conviction check.
      "preopen" -- source premarket_price + prev_close from a single batch
                   get_preopen_snapshot() call (Upstox pre-open IEP). Filter-4
                   is skipped (no intraday bars exist yet). Per-symbol
                   enrichment (prev_volume, ATR) runs only on the shortlist.
                   Returns [] if the snapshot is empty so the caller degrades
                   to a 09:15-only scan.
    """
    universe = get_universe()

    if price_source == "preopen":
        return _scan_preopen(universe)
    else:
        return _scan_live(universe)


def _scan_preopen(universe: list[dict]) -> list[GapCandidate]:
    """
    Pre-open path: batch snapshot → cheap gap filter → enrich shortlist only.

    This keeps total HTTP round-trips to:
      1 batch snapshot call + len(shortlist) enrichment calls (~20–40).
    """
    symbols = [s.get("symbol") for s in universe if s.get("symbol")]
    sector_map = {s["symbol"]: s.get("sector", "UNKNOWN") for s in universe}

    # --- Step 1: one batch call for gap info ---
    snapshot = fetcher.get_preopen_snapshot(symbols)
    if not snapshot:
        logger.warning("Pre-open snapshot empty -- skipping provisional scan")
        return []

    # --- Step 2: cheap filters (gap size + price band) on full universe ---
    cheap_candidates = []
    for symbol in symbols:
        snap = snapshot.get(symbol)
        if snap is None:
            continue
        premarket_price = snap.get("price")
        prev_close = snap.get("prev_close")
        if premarket_price is None or prev_close is None or prev_close <= 0:
            continue

        gap_pct = (premarket_price - prev_close) / prev_close * 100

        # Filter 1: gap size
        if abs(gap_pct) < config.GAP_MIN_PCT or abs(gap_pct) > config.GAP_MAX_PCT:
            continue

        # Filter 3: price band
        if premarket_price < config.MIN_PRICE or premarket_price > config.MAX_PRICE:
            continue

        # Preliminary gap_score (no volume yet)
        preliminary_score = abs(gap_pct)
        cheap_candidates.append((preliminary_score, symbol, premarket_price, prev_close, gap_pct))

    if not cheap_candidates:
        logger.warning("Pre-open: no symbols passed gap+price filters")
        return []

    # Sort by preliminary gap size and take a shortlist for enrichment
    cheap_candidates.sort(key=lambda x: x[0], reverse=True)
    shortlist = cheap_candidates[:_PREOPEN_SHORTLIST_SIZE]
    logger.info(
        "Pre-open: %d symbols in gap range → enriching top %d shortlist",
        len(cheap_candidates),
        len(shortlist),
    )

    # --- Step 3: enrich shortlist (prev_volume, ATR) ---
    candidates: list[GapCandidate] = []
    for _, symbol, premarket_price, prev_close, gap_pct in shortlist:
        sector = sector_map.get(symbol, "UNKNOWN")
        try:
            hist = fetcher.get_historical_data(symbol, period="5d")
            if len(hist) < 2:
                continue

            prev_volume = hist["Volume"].iloc[-2]

            # Filter 2: previous day volume
            if prev_volume < config.MIN_PREV_VOLUME:
                logger.debug("%s: prev_volume %d < %d -- skipped", symbol, int(prev_volume), config.MIN_PREV_VOLUME)
                continue

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
            logger.warning("AgentI1 pre-open enrich error %s: %s", symbol, exc)
            continue

    if len(candidates) < 3:
        logger.warning("Pre-open: fewer than 3 enriched candidates -- NO_TRADE_DAY")
        return []

    candidates.sort(key=lambda c: c.gap_score, reverse=True)
    result = candidates[: config.MAX_GAP_CANDIDATES]
    logger.info(
        "AgentI1 pre-open: %d enriched → top %d selected",
        len(candidates),
        len(result),
    )
    return result


def _scan_live(universe: list[dict]) -> list[GapCandidate]:
    """
    Live path (09:15+ candles available): per-symbol fetch with volume confirm.
    Called after market open to use actual first-candle gaps.
    """
    candidates: list[GapCandidate] = []

    for stock in universe:
        symbol = stock.get("symbol")
        sector = stock.get("sector", "UNKNOWN")

        if not symbol:
            continue

        try:
            prev_close = fetcher.get_previous_close(symbol)
            if prev_close is None:
                continue

            hist = fetcher.get_historical_data(symbol, period="5d")
            if len(hist) < 2:
                continue

            prev_volume = hist["Volume"].iloc[-2]

            intraday_df = fetcher.get_intraday_candles(symbol)
            if intraday_df is not None and not intraday_df.empty:
                premarket_price = float(intraday_df["Open"].iloc[0])
            else:
                premarket_price = fetcher.get_premarket_price(symbol)
            if premarket_price is None:
                continue

            gap_pct = (premarket_price - prev_close) / prev_close * 100

            # Filter 1: gap size
            if abs(gap_pct) < config.GAP_MIN_PCT or abs(gap_pct) > config.GAP_MAX_PCT:
                continue

            # Filter 2: previous day volume
            if prev_volume < config.MIN_PREV_VOLUME:
                continue

            # Filter 3: price band
            if premarket_price < config.MIN_PRICE or premarket_price > config.MAX_PRICE:
                continue

            # Filter 4: today's volume ratio (conviction filter)
            if intraday_df is not None and not intraday_df.empty:
                vol_ratio = Indicators.volume_ratio(intraday_df, lookback=20)
                if vol_ratio > 0 and vol_ratio < config.MIN_VOLUME_RATIO:
                    logger.debug(
                        "%s: volume_ratio=%.2f < %.2f -- low conviction, skipped",
                        symbol, vol_ratio, config.MIN_VOLUME_RATIO,
                    )
                    continue

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
