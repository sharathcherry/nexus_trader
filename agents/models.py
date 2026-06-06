"""
Shared data models for nexus_trader pre-market agents.

Pydantic models: used as Gemini structured output schemas (response_schema=).
Dataclasses: pipeline data transfer objects between agents I0→I1→I2→I3.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pydantic models — Gemini structured output schemas
# ---------------------------------------------------------------------------


class MarketBias(BaseModel):
    """AgentI0 output: global market bias classification from Gemini Flash."""

    bias: str  # "BULLISH" / "BEARISH" / "NEUTRAL"
    bias_strength: float  # 0.0–1.0
    gift_nifty_gap_pct: float  # Gift Nifty implied open gap %
    valid_strategies: list[str]  # e.g. ["GAP_AND_GO", "ORB_BREAKOUT"]
    confidence: float  # 0.0–1.0; if < 0.5 → bias overridden to NEUTRAL


class NewsAnalysis(BaseModel):
    """AgentI2 output: per-stock news catalyst classification from Gemini Flash."""

    catalyst_type: str  # "EARNINGS" / "BROKER_UPGRADE" / "BLOCK_DEAL" / "INDEX_REBALANCE" / "MACRO" / "UNKNOWN"
    trade_recommendation: str  # "TRADE" / "AVOID" / "UNKNOWN"
    summary: str  # brief 1-sentence summary of the catalyst


# ---------------------------------------------------------------------------
# Dataclasses — pipeline data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class GapCandidate:
    """
    Output of AgentI1 gap scanner.

    One entry per stock that passes gap filter (1.5–8%, volume ≥ 500k, price ₹50–₹5000).
    Mutable: AgentI2 writes catalyst_type and trade_recommendation in-place.
    """

    symbol: str
    sector: str
    prev_close: float
    premarket_price: float
    gap_pct: float  # positive = gap-up, negative = gap-down
    prev_volume: int
    gap_score: float  # abs(gap_pct) * min(prev_volume / 500_000, 3.0)
    catalyst_type: str = field(default="UNKNOWN")
    trade_recommendation: str = field(default="UNKNOWN")


@dataclass
class WatchlistEntry:
    """
    Final watchlist entry produced by AgentI3.

    Includes strategy assignment, ATR-based price levels, and R:R filter result.
    Consumed by AgentI4 (Phase 4b) signal engine and Phase 5 orchestrator.
    """

    symbol: str
    sector: str
    gap_pct: float
    gap_score: float
    strategy: str  # "GAP_AND_GO" / "ORB_BREAKOUT" / "GAP_FILL" / "VWAP_RECLAIM"
    entry_trigger: float  # price level that confirms entry
    stop_loss: float
    target: float
    rr_ratio: float  # (target - entry_trigger) / (entry_trigger - stop_loss)
    catalyst_type: str
    atr: float  # 14-period daily ATR used for price level calculation
