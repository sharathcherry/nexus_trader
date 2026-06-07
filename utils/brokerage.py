"""
utils/brokerage.py — Consolidated Zerodha intraday brokerage math.
"""

def calculate_brokerage(buy_price: float, sell_price: float, qty: int) -> dict:
    """
    Compute Zerodha intraday brokerage breakdown.

    Formula (exchange rate 0.0000307):
      turnover         = (buy_price + sell_price) * qty
      brokerage        = min(20, 0.0003 * turnover)
      stt              = 0.00025 * sell_price * qty  (sell-side only)
      exchange_charges = 0.0000307 * turnover
      gst              = 0.18 * brokerage
      total_charges    = sum of all four
    """
    buy_turnover = buy_price * qty
    sell_turnover = sell_price * qty
    turnover = buy_turnover + sell_turnover

    brokerage = min(20.0, 0.0003 * turnover)
    stt = 0.00025 * sell_turnover
    exchange_charges = 0.0000307 * turnover
    gst = 0.18 * brokerage
    total_charges = brokerage + stt + exchange_charges + gst

    return {
        "brokerage": round(brokerage, 4),
        "stt": round(stt, 4),
        "exchange_charges": round(exchange_charges, 4),
        "exchange": round(exchange_charges, 4),  # compatibility alias for backtester.py
        "gst": round(gst, 4),
        "total_charges": round(total_charges, 4),
    }
