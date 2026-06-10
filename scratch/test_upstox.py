import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("UPSTOX_ACCESS_TOKEN")

headers = {
    'Accept': 'application/json',
    'Authorization': f'Bearer {token}'
}

# Try getting a quote for Reliance
url = 'https://api.upstox.com/v2/market-quote/quotes?instrument_key=NSE_EQ|RELIANCE'
response = requests.get(url, headers=headers)
print("By Symbol:", response.json())

print("Testing instruments download...")
resp = requests.get("https://assets.upstox.com/tsl/instruments/instruments.json.gz", stream=True)
print(resp.status_code)
if resp.status_code == 200:
    print("Found JSON.GZ")
else:
    resp = requests.get("https://assets.upstox.com/tsl/instruments/instruments.json", stream=True)
    print("JSON:", resp.status_code)
