"""
utils/brokerage.py — Consolidated Zerodha intraday brokerage math.
"""

def calculate_brokerage(buy_price: float, sell_price: float, qty: int) -> dict:
    """
    Compute Zerodha intraday brokerage breakdown.

    Formula:
      buy_turnover     = buy_price * qty
      sell_turnover    = sell_price * qty
      turnover         = buy_turnover + sell_turnover
      brokerage        = min(20, 0.0003 * buy_turnover) + min(20, 0.0003 * sell_turnover)
      stt              = 0.00025 * sell_turnover  (sell-side only)
      exchange_charges = 0.0000345 * turnover
      sebi_charges     = 0.000001 * turnover (Rs 10 per crore)
      stamp_duty       = 0.00003 * buy_turnover (0.003% on buy side)
      gst              = 0.18 * (brokerage + exchange_charges + sebi_charges)
      total_charges    = sum of all above
    """
    buy_turnover = buy_price * qty
    sell_turnover = sell_price * qty
    turnover = buy_turnover + sell_turnover

    brokerage = min(20.0, 0.0003 * buy_turnover) + min(20.0, 0.0003 * sell_turnover)
    stt = 0.00025 * sell_turnover
    exchange_charges = 0.0000345 * turnover
    sebi_charges = 0.000001 * turnover
    stamp_duty = 0.00003 * buy_turnover
    gst = 0.18 * (brokerage + exchange_charges + sebi_charges)
    
    total_charges = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst

    return {
        "brokerage": round(brokerage, 4),
        "stt": round(stt, 4),
        "exchange_charges": round(exchange_charges, 4),
        "exchange": round(exchange_charges, 4),  # compatibility alias for backtester.py
        "sebi": round(sebi_charges, 4),
        "stamp": round(stamp_duty, 4),
        "gst": round(gst, 4),
        "total_charges": round(total_charges, 4),
    }
