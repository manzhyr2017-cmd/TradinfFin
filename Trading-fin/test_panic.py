
import requests
import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("CRYPTOPANIC_KEY")
print(f"Key: {key[:5]}...")

urls = [
    f"https://cryptopanic.com/api/v1/posts/?auth_token={key}",
    f"https://cryptopanic.com/api/v1/posts?auth_token={key}",
    f"https://cryptopanic.com/api/posts/?auth_token={key}",
    f"https://cryptopanic.com/api/posts?auth_token={key}"
]

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
for url in urls:
    try:
        r = requests.get(url, headers=headers, timeout=5)
        print(f"URL: {url} | Status: {r.status_code}")
        if r.status_code == 200:
             print(f"  SUCCESS! Sample: {r.text[:50]}")
    except Exception as e:
        print(f"URL: {url} | Error: {e}")
