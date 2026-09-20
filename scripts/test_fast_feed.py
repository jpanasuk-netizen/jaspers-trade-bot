import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.fast_feed import _fetch_kalshi_book_race, _fetch_spot_race  # noqa: E402
from app.market import snapshot  # noqa: E402

print("=== spot race ===")
t0 = time.perf_counter()
spot = _fetch_spot_race()
print(
    f"wall {(time.perf_counter()-t0)*1000:.0f}ms",
    json.dumps(
        {k: spot.get(k) for k in ("price", "source", "latency_ms", "all_latency_ms", "errors")},
        indent=2,
    )[:700],
)

print("\n=== kalshi race ===")
t0 = time.perf_counter()
book = _fetch_kalshi_book_race()
act = book.get("active") or {}
print(
    f"wall {(time.perf_counter()-t0)*1000:.0f}ms ok={book.get('ok')} "
    f"count={book.get('count')} lat={book.get('latency_ms')} url={book.get('source_url')}"
)
print(
    "active",
    {
        k: act.get(k)
        for k in (
            "ticker",
            "yes_bid",
            "yes_ask",
            "no_bid",
            "no_ask",
            "yes_mid",
            "open_of_window",
            "seconds_left",
        )
    },
)

print("\n=== market.snapshot (fast path) ===")
for i in range(3):
    t0 = time.perf_counter()
    s = snapshot()
    print(
        f"[{i}] {(time.perf_counter()-t0)*1000:.0f}ms",
        json.dumps(
            {
                "spot_src": (s.get("spot") or {}).get("source"),
                "price": (s.get("spot") or {}).get("price"),
                "ticker": (s.get("window") or {}).get("ticker"),
                "yes_mid": (s.get("window") or {}).get("yes_mid"),
                "fair": s.get("fast_feed", {}).get("fair_yes"),
                "edge": s.get("fast_feed", {}).get("edge_vs_book"),
                "lat": s.get("fast_feed", {}).get("latency"),
                "src": s.get("fast_feed", {}).get("source"),
            }
        )[:450],
    )
    time.sleep(0.3)
