"""
AgentI2 — News Catalyst Classification Agent.

Runs post-AgentI1. For each GapCandidate, fetches news headlines via Google
News RSS (yfinance .news is IP-blocked on the VM) and calls Gemini Flash to
classify the catalyst type and trade recommendation.

Filters out candidates with catalyst_type in {BLOCK_DEAL, INDEX_REBALANCE}
or trade_recommendation == AVOID. Returns filtered candidate list.

1s asyncio.sleep between Gemini calls to respect free-tier TPM budget.
Gemini failure on a single stock returns UNKNOWN — does not abort loop.

Decision refs: D-05 through D-08 (04A-CONTEXT.md)
"""

import asyncio

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


def _fetch_headlines(symbol: str, limit: int = 5) -> list[str]:
    """Fetch recent news headlines for an NSE symbol via Google News RSS.

    yfinance `.news` is IP-blocked on the production VM (Yahoo), so the news
    filter was silently dead. Google News RSS is key-free and reachable. Returns
    [] on any failure -- the caller treats that as 'no news' -> UNKNOWN
    (fail-open), so a fetch outage never blocks a candidate.
    """
    import urllib.parse
    import urllib.request
    import xml.etree.ElementTree as ET

    term = symbol[:-3] if symbol.endswith(".NS") else symbol
    query = urllib.parse.quote(f'"{term}" stock NSE')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
        # Only <item><title> entries (skips the channel/feed title).
        titles = [t.text for t in root.findall(".//item/title") if t.text]
        return titles[:limit]
    except Exception as exc:
        logger.debug("Google News RSS failed for %s: %s", symbol, exc)
        return []


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
        headlines = _fetch_headlines(candidate.symbol)

        if not headlines:
            logger.debug(f"{candidate.symbol}: no news — skipping Gemini call")
            return NewsAnalysis(
                catalyst_type="UNKNOWN",
                trade_recommendation="UNKNOWN",
                summary="No news found",
            )

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
            ),
        )

        import json
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            parsed_dict = json.loads(text)
        except json.JSONDecodeError:
            # Fallback for completely invalid responses
            raise ValueError(f"Failed to parse JSON: {text}")

        return NewsAnalysis(
            catalyst_type=parsed_dict.get("catalyst_type", "UNKNOWN"),
            trade_recommendation=parsed_dict.get("trade_recommendation", "UNKNOWN"),
            summary=parsed_dict.get("summary", "Unknown"),
        )

    except Exception as e:
        logger.warning(f"{candidate.symbol}: Gemini classification failed ({e})")
        return NewsAnalysis(
            catalyst_type="UNKNOWN",
            trade_recommendation="UNKNOWN",
            summary="Classification failed",
        )
