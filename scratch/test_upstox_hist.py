import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
token = os.getenv("UPSTOX_ACCESS_TOKEN")

headers = {
    'Accept': 'application/json',
    'Authorization': f'Bearer {token}'
}

# Test intraday 5 min
url = "https://api.upstox.com/v2/historical-candle/intraday/NSE_EQ|INE002A01018/1minute"
resp = requests.get(url, headers=headers)
print("Intraday 5min status:", resp.status_code)
print("Intraday 5min error:", resp.json())


# Test historical daily
to_date = datetime.now().strftime('%Y-%m-%d')
from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
url = f"https://api.upstox.com/v2/historical-candle/NSE_EQ|INE002A01018/day/{to_date}/{from_date}"
resp = requests.get(url, headers=headers)
print("\nHistorical daily status:", resp.status_code)
if resp.status_code == 200:
    data = resp.json().get('data', {}).get('candles', [])
    print("Historical daily data points:", len(data))
    if data: print("Sample:", data[0])
