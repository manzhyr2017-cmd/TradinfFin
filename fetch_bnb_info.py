
import requests
import json

url = "https://api.bybit.com/v5/market/instruments-info?category=linear&symbol=BNBUSDT"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
response = requests.get(url, headers=headers)
print(json.dumps(response.json(), indent=2))
