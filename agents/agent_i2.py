"""
AgentI2 — News Catalyst Classification Agent.

Runs post-AgentI1. For each GapCandidate, fetches yfinance news headlines
and calls Gemini Flash to classify the catalyst type and trade recommendation.

Filters out candidates with catalyst_type in {BLOCK_DEAL, INDEX_REBALANCE}
or trade_recommendation == AVOID. Returns filtered candidate list.

1s asyncio.sleep between Gemini calls to respect free-tier TPM budget.
Gemini failure on a single stock returns UNKNOWN — does not abort loop.

Decision refs: D-05 through D-08 (04A-CONTEXT.md)
"""

import asyncio

import yfinance as yf
from google import genai
from google.genai import types

from agents.models import GapCandidate, NewsAnalysis
from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client

_FILTER_CATALYSTS = {"BLOCK_DEAL", "INDEX_REBALANCE"}


async def run(candidates: list[GapCandidate]) -> list[GapCandidate]:
    """
    Main entry point for AgentI2.

    Returns filtered list[GapCandidate] with catalyst_type and trade_recommendation
    populated. Never raises.
    """
    if not candidates:
        return []

    logger.info(f"AgentI2 processing {len(candidates)} candidates")

    for candidate in candidates:
        await asyncio.sleep(1)  # 1s between Gemini calls — rate limit (D-05)
        result = await asyncio.to_thread(_classify_news, candidate)
        candidate.catalyst_type = result.catalyst_type
        candidate.trade_recommendation = result.trade_recommendation

    filtered = [
        c
        for c in candidates
        if c.catalyst_type not in _FILTER_CATALYSTS
        and c.trade_recommendation != "AVOID"
    ]

    logger.info(
        f"AgentI2: {len(filtered)}/{len(candidates)} candidates passed news filter"
    )
    return filtered


def _classify_news(candidate: GapCandidate) -> NewsAnalysis:
    """
    Fetch yfinance news headlines, classify via Gemini Flash.

    Returns NewsAnalysis with catalyst_type="UNKNOWN" on any failure or empty news.
    Never raises — all exceptions caught and logged.
    """
    try:
        ticker = yf.Ticker(candidate.symbol)
        news_items = ticker.news or []

        if not news_items:
            logger.debug(f"{candidate.symbol}: no news — skipping Gemini call")
            return NewsAnalysis(
                catalyst_type="UNKNOWN",
                trade_recommendation="UNKNOWN",
                summary="No news found",
            )

        headlines = [
            item.get("title", "")
            for item in news_items[:5]
            if item.get("title")
        ]

        prompt = (
            f"Analyze these news headlines for {candidate.symbol} (Indian stock, NSE listed):\n"
            + "\n".join(f"- {h}" for h in headlines)
            + "\n\n"
            "Classify the catalyst type and trading recommendation.\n"
            "catalyst_type: one of EARNINGS, BROKER_UPGRADE, BROKER_DOWNGRADE, "
            "BLOCK_DEAL, INDEX_REBALANCE, MACRO, CORPORATE_ACTION, UNKNOWN\n"
            "trade_recommendation: one of TRADE, AVOID, UNKNOWN\n"
            "summary: brief 1-sentence summary of the catalyst"
        )

        response = _get_client().models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=NewsAnalysis,
            ),
        )

        result = response.parsed
        if result is None:
            raise ValueError("response.parsed is None")

        return result

    except Exception as e:
        logger.warning(f"{candidate.symbol}: Gemini classification failed ({e})")
        return NewsAnalysis(
            catalyst_type="UNKNOWN",
            trade_recommendation="UNKNOWN",
            summary="Classification failed",
        )
