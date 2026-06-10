import json
import yfinance as yf
from data.universe import _NSE_UNIVERSE

mapping = {}
for item in _NSE_UNIVERSE:
    sym = item["symbol"]
    try:
        t = yf.Ticker(sym)
        isin = t.isin
        if isin:
            mapping[sym] = f"NSE_EQ|{isin}"
            print(f"{sym} -> {mapping[sym]}")
        else:
            print(f"Failed to get ISIN for {sym}")
    except Exception as e:
        print(f"Error {sym}: {e}")

with open("upstox_map.json", "w") as f:
    json.dump(mapping, f, indent=4)
