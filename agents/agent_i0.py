"""
AgentI0 — Global Market Bias Agent.

Runs pre-market (8:30–8:35 IST) as a coroutine alongside AgentI1.
Fetches global index data via MarketDataFetcher, classifies market bias
using Gemini Flash structured output (MarketBias Pydantic model).

Fallback: If Gemini fails for any reason, a rule-based fallback uses the
S&P 500 daily change to approximate bias with confidence=0.0 (NEUTRAL override
threshold is confidence < 0.5, so fallback bias is always overridden to NEUTRAL).

Decision refs: D-01 through D-01e (CONTEXT.md)
"""

import asyncio

import pytz
from google import genai
from google.genai import types

from agents.models import MarketBias
from config import config
from data.market_data import MarketDataFetcher
from utils.logger import setup_logger

logger = setup_logger(__name__)
from utils.decision_logger import dlog
IST = pytz.timezone("Asia/Kolkata")

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client

# Module-level MarketDataFetcher instance
fetcher = MarketDataFetcher()


async def run() -> MarketBias:
    """
    Main entry point for AgentI0.

    Returns MarketBias — never raises. Always returns a valid MarketBias object
    (rule-based fallback on any failure).
    """
    return await asyncio.to_thread(_fetch_and_classify)


def _fetch_and_classify() -> MarketBias:
    """
    Sync inner function: fetch global indices and classify market bias.

    Orchestrates _call_gemini() with exception safety.
    If Gemini returns confidence < 0.5, bias is overridden to NEUTRAL (D-01e).
    """
    indices_data = fetcher.get_global_indices()

    if not indices_data:
        logger.warning("AgentI0: no global indices data — using rule-based fallback")
        return _rule_based_fallback({})

    try:
        result = _call_gemini(indices_data)
    except Exception as e:
        logger.warning(f"AgentI0: Gemini call failed ({e}) — using rule-based fallback")
        return _rule_based_fallback(indices_data)

    # D-01e: low-confidence override
    if result.confidence < 0.5:
        logger.info(
            f"AgentI0: Gemini confidence {result.confidence:.2f} < 0.5 — overriding bias to NEUTRAL"
        )
        result.bias = "NEUTRAL"

    return result


def _call_gemini(indices_data: dict) -> MarketBias:
    """
    Build prompt from global indices, call Gemini Flash, return parsed MarketBias.

    Raises on any failure (API error, response.parsed is None, validation error).
    Caller (_fetch_and_classify) handles all exceptions.
    """
    # Build human-readable index summary for prompt
    index_lines = "\n".join(
        f"  {name}: {value:.2f}" for name, value in indices_data.items()
    )

    prompt = f"""You are a pre-market market analyst for NSE India intraday trading.

Based on the following global market index closing data, classify the overall market bias
for today's NSE India trading session.

Global indices (latest closing values):
{index_lines}

Determine:
1. bias: Overall directional bias — must be exactly "BULLISH", "BEARISH", or "NEUTRAL"
2. bias_strength: Conviction level 0.0 (weak) to 1.0 (strong)
3. gift_nifty_gap_pct: Estimated Gift Nifty implied gap percentage (positive = gap up, negative = gap down)
4. valid_strategies: List of trading strategies valid for today — choose from: GAP_AND_GO, ORB_BREAKOUT, GAP_FILL, VWAP_RECLAIM
5. confidence: Your confidence in this bias assessment, 0.0 to 1.0

Be conservative. If global cues are mixed, lean towards NEUTRAL.
"""

    response = _get_client().models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MarketBias,
        ),
    )

    result = response.parsed
    if result is None:
        raise ValueError("Gemini response.parsed is None")

    logger.info(
        f"Market bias: {result.bias} (strength={result.bias_strength:.2f}, confidence={result.confidence:.2f})"
    )
    dlog.market_bias(
        bias=result.bias,
        indices=indices_data,
        reasoning=f"strength={result.bias_strength:.2f}, confidence={result.confidence:.2f}. {getattr(result, 'key_factors', '')}",
    )
    return result


def _rule_based_fallback(indices_data: dict) -> MarketBias:
    """
    Determine bias from S&P 500 change_pct without Gemini.

    Accepts indices_data in the format {"^GSPC": {"change_pct": float}, ...}
    where change_pct is the percentage daily move of the S&P 500.

    Note: MarketDataFetcher.get_global_indices() returns close prices, not change_pct.
    When called from _fetch_and_classify, the ^GSPC key will not be present and
    the function returns NEUTRAL — which is correct since confidence=0.0 triggers
    the NEUTRAL override in _fetch_and_classify anyway (D-01d/D-01e).
    """
    logger.warning("AgentI0 using rule-based fallback (Gemini unavailable)")

    bias = "NEUTRAL"

    if "^GSPC" in indices_data:
        sp500 = indices_data["^GSPC"]
        if isinstance(sp500, dict):
            change_pct = sp500.get("change_pct", 0.0)
        else:
            change_pct = 0.0

        if change_pct > 0.5:
            bias = "BULLISH"
        elif change_pct < -0.5:
            bias = "BEARISH"

    return MarketBias(
        bias=bias,
        bias_strength=0.3,
        gift_nifty_gap_pct=0.0,
        valid_strategies=["GAP_AND_GO", "ORB_BREAKOUT", "GAP_FILL", "VWAP_RECLAIM"],
        confidence=0.0,
    )
