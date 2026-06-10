import json
import gzip
import urllib.request
from data.universe import _NSE_UNIVERSE

url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
print("Downloading instruments.json.gz...")
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as response:
    with open("instruments.json.gz", "wb") as f:
        f.write(response.read())

print("Parsing...")
with gzip.open("instruments.json.gz", "rt", encoding="utf-8") as f:
    data = json.load(f)

# Build a fast lookup by trading_symbol -> instrument_key
# The symbol in upstox is usually "RELIANCE", "TCS", "INFY" without the ".NS"
upstox_dict = {}
for item in data:
    if item.get("segment") == "NSE_EQ":
        sym = item.get("trading_symbol")
        upstox_dict[sym] = item.get("instrument_key")

mapping = {}
for item in _NSE_UNIVERSE:
    y_sym = item["symbol"]
    u_sym = y_sym.replace(".NS", "")
    # Some symbols might differ slightly like M&M vs M&M, LTIM vs LTIM
    if u_sym in upstox_dict:
        mapping[y_sym] = upstox_dict[u_sym]
        print(f"Mapped {y_sym} -> {mapping[y_sym]}")
    else:
        print(f"Could not map {y_sym}")

with open("data/upstox_map.json", "w") as f:
    json.dump(mapping, f, indent=4)
print(f"Mapped {len(mapping)} / {len(_NSE_UNIVERSE)} symbols.")
