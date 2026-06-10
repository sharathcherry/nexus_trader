import requests
import gzip
import csv
import json

url = "https://assets.upstox.com/tsl/instruments/instruments.csv.gz"
filename = "instruments.csv.gz"

print("Downloading...")
response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
with open(filename, 'wb') as f:
    f.write(response.content)

print("Parsing...")
symbol_to_key = {}
with gzip.open(filename, 'rt', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['exchange'] == 'NSE_EQ':
            symbol = row['tradingsymbol']
            key = row['instrument_key']
            symbol_to_key[symbol] = key

print(f"Loaded {len(symbol_to_key)} NSE_EQ instruments.")
print("RELIANCE:", symbol_to_key.get('RELIANCE'))
print("TCS:", symbol_to_key.get('TCS'))

with open('upstox_instruments.json', 'w') as f:
    json.dump(symbol_to_key, f)
