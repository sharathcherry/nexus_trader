import os
from dotenv import load_dotenv
load_dotenv()

from data.market_data import MarketDataFetcher
fetcher = MarketDataFetcher()

print("Testing RELIANCE.NS (Upstox)...")
c = fetcher.get_previous_close("RELIANCE.NS")
print("Previous close:", c)
pm = fetcher.get_premarket_price("RELIANCE.NS")
print("Premarket open:", pm)
df = fetcher.get_intraday_candles("RELIANCE.NS")
print("Intraday rows:", len(df))

print("\nTesting TATAMOTORS.NS (yfinance fallback)...")
c2 = fetcher.get_previous_close("TATAMOTORS.NS")
print("TATAMOTORS previous close:", c2)
