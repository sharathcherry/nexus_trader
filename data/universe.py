"""
NSE Nifty 100 universe — hardcoded static list.

This module contains the complete Nifty 100 universe as a Python list of dicts.
Zero file I/O at startup, version-controlled, grep-friendly.
Update quarterly when Nifty 100 constituents change.

Last updated: 2026-06-06
"""

_NSE_UNIVERSE = [
    # Energy (8)
    {"symbol": "RELIANCE.NS", "sector": "Energy"},
    {"symbol": "ONGC.NS", "sector": "Energy"},
    {"symbol": "NTPC.NS", "sector": "Energy"},
    {"symbol": "POWERGRID.NS", "sector": "Energy"},
    {"symbol": "BPCL.NS", "sector": "Energy"},
    {"symbol": "IOC.NS", "sector": "Energy"},
    {"symbol": "GAIL.NS", "sector": "Energy"},
    {"symbol": "COALINDIA.NS", "sector": "Energy"},
    # Financial Services (11)
    {"symbol": "HDFCBANK.NS", "sector": "Financial Services"},
    {"symbol": "ICICIBANK.NS", "sector": "Financial Services"},
    {"symbol": "KOTAKBANK.NS", "sector": "Financial Services"},
    {"symbol": "AXISBANK.NS", "sector": "Financial Services"},
    {"symbol": "SBIN.NS", "sector": "Financial Services"},
    {"symbol": "BAJFINANCE.NS", "sector": "Financial Services"},
    {"symbol": "BAJAJFINSV.NS", "sector": "Financial Services"},
    {"symbol": "HDFCLIFE.NS", "sector": "Financial Services"},
    {"symbol": "SBILIFE.NS", "sector": "Financial Services"},
    {"symbol": "SHRIRAMFIN.NS", "sector": "Financial Services"},
    {"symbol": "INDUSINDBK.NS", "sector": "Financial Services"},
    # IT (7)
    {"symbol": "TCS.NS", "sector": "IT"},
    {"symbol": "INFY.NS", "sector": "IT"},
    {"symbol": "HCLTECH.NS", "sector": "IT"},
    {"symbol": "WIPRO.NS", "sector": "IT"},
    {"symbol": "TECHM.NS", "sector": "IT"},
    {"symbol": "LTIM.NS", "sector": "IT"},
    {"symbol": "MPHASIS.NS", "sector": "IT"},
    # FMCG (9)
    {"symbol": "HINDUNILVR.NS", "sector": "FMCG"},
    {"symbol": "ITC.NS", "sector": "FMCG"},
    {"symbol": "NESTLEIND.NS", "sector": "FMCG"},
    {"symbol": "BRITANNIA.NS", "sector": "FMCG"},
    {"symbol": "DABUR.NS", "sector": "FMCG"},
    {"symbol": "MARICO.NS", "sector": "FMCG"},
    {"symbol": "COLPAL.NS", "sector": "FMCG"},
    {"symbol": "TATACONSUM.NS", "sector": "FMCG"},
    {"symbol": "GODREJCP.NS", "sector": "FMCG"},
    # Auto (7)
    {"symbol": "MARUTI.NS", "sector": "Auto"},
    {"symbol": "TATAMOTORS.NS", "sector": "Auto"},
    {"symbol": "M&M.NS", "sector": "Auto"},
    {"symbol": "BAJAJ-AUTO.NS", "sector": "Auto"},
    {"symbol": "EICHERMOT.NS", "sector": "Auto"},
    {"symbol": "HEROMOTOCO.NS", "sector": "Auto"},
    {"symbol": "TVSMOTOR.NS", "sector": "Auto"},
    # Pharma (8)
    {"symbol": "SUNPHARMA.NS", "sector": "Pharma"},
    {"symbol": "DRREDDY.NS", "sector": "Pharma"},
    {"symbol": "CIPLA.NS", "sector": "Pharma"},
    {"symbol": "DIVISLAB.NS", "sector": "Pharma"},
    {"symbol": "APOLLOHOSP.NS", "sector": "Pharma"},
    {"symbol": "LUPIN.NS", "sector": "Pharma"},
    {"symbol": "TORNTPHARM.NS", "sector": "Pharma"},
    {"symbol": "AUROPHARMA.NS", "sector": "Pharma"},
    # Metals (5)
    {"symbol": "TATASTEEL.NS", "sector": "Metals"},
    {"symbol": "JSWSTEEL.NS", "sector": "Metals"},
    {"symbol": "HINDALCO.NS", "sector": "Metals"},
    {"symbol": "VEDL.NS", "sector": "Metals"},
    {"symbol": "SAIL.NS", "sector": "Metals"},
    # Telecom (1)
    {"symbol": "BHARTIARTL.NS", "sector": "Telecom"},
    # Infra (7)
    {"symbol": "LT.NS", "sector": "Infra"},
    {"symbol": "ADANIPORTS.NS", "sector": "Infra"},
    {"symbol": "ADANIGREEN.NS", "sector": "Infra"},
    {"symbol": "ADANIENT.NS", "sector": "Infra"},
    {"symbol": "SIEMENS.NS", "sector": "Infra"},
    {"symbol": "ABB.NS", "sector": "Infra"},
    {"symbol": "BEL.NS", "sector": "Infra"},
    # Cement (5)
    {"symbol": "ULTRACEMCO.NS", "sector": "Cement"},
    {"symbol": "GRASIM.NS", "sector": "Cement"},
    {"symbol": "AMBUJACEM.NS", "sector": "Cement"},
    {"symbol": "ACC.NS", "sector": "Cement"},
    {"symbol": "SHREECEM.NS", "sector": "Cement"},
    # Consumer Durables (4)
    {"symbol": "TITAN.NS", "sector": "Consumer Durables"},
    {"symbol": "HAVELLS.NS", "sector": "Consumer Durables"},
    {"symbol": "VOLTAS.NS", "sector": "Consumer Durables"},
    {"symbol": "WHIRLPOOL.NS", "sector": "Consumer Durables"},
    # Chemicals (3)
    {"symbol": "PIDILITIND.NS", "sector": "Chemicals"},
    {"symbol": "ASIANPAINT.NS", "sector": "Chemicals"},
    {"symbol": "BERGERPAINTS.NS", "sector": "Chemicals"},
    # Media / Realty (6)
    {"symbol": "ZOMATO.NS", "sector": "Others"},
    {"symbol": "NYKAA.NS", "sector": "Media"},
    {"symbol": "PAYTM.NS", "sector": "Media"},
    {"symbol": "DLF.NS", "sector": "Realty"},
    {"symbol": "GODREJPROP.NS", "sector": "Realty"},
    {"symbol": "OBEROIRLTY.NS", "sector": "Realty"},
    # Others (19)
    {"symbol": "INDIGO.NS", "sector": "Infra"},
    {"symbol": "TRENT.NS", "sector": "FMCG"},
    {"symbol": "DMART.NS", "sector": "FMCG"},
    {"symbol": "MOTHERSON.NS", "sector": "Auto"},
    {"symbol": "MRF.NS", "sector": "Auto"},
    {"symbol": "BALKRISIND.NS", "sector": "Auto"},
    {"symbol": "BOSCHLTD.NS", "sector": "Auto"},
    {"symbol": "CGPOWER.NS", "sector": "Infra"},
    {"symbol": "CUMMINSIND.NS", "sector": "Infra"},
    {"symbol": "HDFCAMC.NS", "sector": "Financial Services"},
    {"symbol": "ICICIGI.NS", "sector": "Financial Services"},
    {"symbol": "MUTHOOTFIN.NS", "sector": "Financial Services"},
    {"symbol": "PFC.NS", "sector": "Financial Services"},
    {"symbol": "RECLTD.NS", "sector": "Financial Services"},
    {"symbol": "ZYDUSLIFE.NS", "sector": "Pharma"},
    {"symbol": "NAUKRI.NS", "sector": "IT"},
    {"symbol": "SBICARD.NS", "sector": "Financial Services"},
    {"symbol": "ICICIPRULI.NS", "sector": "Financial Services"},
    {"symbol": "CHOLAFIN.NS", "sector": "Financial Services"},
]


def get_nse_universe() -> list[dict]:
    """Return the Nifty 100 universe as a list of dicts with 'symbol' and 'sector' keys."""
    return [stock.copy() for stock in _NSE_UNIVERSE]


# Build a fast O(1) symbol → sector lookup map at import time
_SYMBOL_SECTOR_MAP: dict[str, str] = {
    stock["symbol"]: stock["sector"] for stock in _NSE_UNIVERSE
}


def get_symbol_sector(symbol: str) -> str | None:
    """Return the sector for a symbol, or None if not found in the universe."""
    return _SYMBOL_SECTOR_MAP.get(symbol)
