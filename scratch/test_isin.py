import yfinance as yf

ticker = yf.Ticker("RELIANCE.NS")
print("ISIN directly:", ticker.isin)
print("ISIN from info:", ticker.info.get('isin'))
