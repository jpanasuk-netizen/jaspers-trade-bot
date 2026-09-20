import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UA = {"User-Agent": "jev-fast/2.0", "Accept": "application/json"}


def probe(url, name):
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=3) as r:
            body = r.read()[:180]
        print(f"OK {(time.perf_counter()-t0)*1000:6.0f}ms {name:14} {body[:140]!r}")
        return True
    except Exception as e:
        print(f"FAIL {(time.perf_counter()-t0)*1000:6.0f}ms {name:14} {type(e).__name__}: {e}")
        return False


print("=== spot probes ===")
spots = [
    ("coinbase_ex", "https://api.exchange.coinbase.com/products/BTC-USD/ticker"),
    ("coinbase_v2", "https://api.coinbase.com/v2/prices/BTC-USD/spot"),
    ("gemini", "https://api.gemini.com/v1/pubticker/btcusd"),
    ("bitstamp", "https://www.bitstamp.net/api/v2/ticker/btcusd/"),
    ("kraken", "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"),
    ("okx", "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT"),
    ("bybit", "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT"),
    ("binance_us", "https://api.binance.us/api/v3/ticker/price?symbol=BTCUSD"),
]
for n, u in spots:
    probe(u, n)

print("\n=== kalshi probes ===")
kals = [
    ("elections_open", "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXBTC15M&status=open&limit=5"),
    ("external_open", "https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXBTC15M&status=open&limit=5"),
    ("trades", "https://api.elections.kalshi.com/trade-api/v2/markets/trades?limit=3&ticker=KXBTC15M"),
]
for n, u in kals:
    probe(u, n)

print("\n=== fast feed parse ===")
from app.fast_feed import _fetch_kalshi_book_race, _fetch_spot_race

spot = _fetch_spot_race()
print("spot", {k: spot.get(k) for k in ("price", "source", "latency_ms", "errors")})
book = _fetch_kalshi_book_race()
act = book.get("active") or {}
print("book", book.get("latency_ms"), book.get("source_url", "")[:70])
print("active", {k: act.get(k) for k in ("ticker", "yes_bid", "yes_ask", "yes_mid", "open_of_window", "seconds_left")})
