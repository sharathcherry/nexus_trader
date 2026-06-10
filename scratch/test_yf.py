import yfinance as yf
import time

tickers = ['RELIANCE.NS', '^GSPC', '^IXIC', 'ONGC.NS']
for t in tickers:
    print(f"Fetching {t}...")
    df = yf.Ticker(t).history(period="5d", interval="1d")
    if df.empty:
        print(f"FAILED {t}")
    else:
        print(f"SUCCESS {t} - {len(df)} rows")
    time.sleep(1.0)
