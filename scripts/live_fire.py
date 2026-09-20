"""Force a live Kalshi order for the active BTC 15m window. Prints response, never keys."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import kalshi_live  # noqa: E402
from app.config import config  # noqa: E402


def main() -> int:
    kid, pk = kalshi_live.load_creds()
    print("creds ok key_id_len", len(kid))

    st, mkts = kalshi_live._kreq(
        kid, pk, "GET",
        "/trade-api/v2/markets?limit=10&series_ticker=KXBTC15M&status=open",
    )
    markets = mkts.get("markets") or []
    print("open_markets", len(markets), "status", st)
    if not markets:
        print("NO_OPEN_MARKET")
        return 2
    markets.sort(key=lambda m: m.get("close_time") or "")
    m = markets[0]
    ticker = m.get("ticker")
    yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0)
    no_ask = float(m.get("no_ask_dollars") or m.get("no_ask") or 0)
    yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
    no_bid = float(m.get("no_bid_dollars") or m.get("no_bid") or 0)
    print("market", ticker, "yes", yes_bid, yes_ask, "no", no_bid, no_ask)

    stb, bal = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/balance")
    avail = None
    for row in bal.get("balance_breakdown") or []:
        if int(row.get("exchange_index", -1)) == config.kalshi_exchange_index:
            avail = float(row.get("balance") or 0)
            break
    if avail is None:
        raw = float(bal.get("balance_dollars") or 0)
        avail = raw / 100.0 if raw > 50 else raw
    print("avail_ex", config.kalshi_exchange_index, avail)

    side = (sys.argv[1] if len(sys.argv) > 1 else "NO").upper()
    # Size 1 contract at a price cash can cover
    if side == "NO":
        want = no_ask or 0.5
        # Kalshi: buy NO — try side=no at no price, fallback ask path
        limit = round(min(0.99, max(0.01, min(want, avail * 0.97))), 4)
        candidates = [
            {"side": "no", "price": limit, "label": "side_no_limit"},
            {"side": "no", "price": round(min(want, 0.99), 4), "label": "side_no_ask"},
            {"side": "ask", "price": round(max(0.01, min(0.99, 1.0 - want)), 4), "label": "side_ask_implied"},
        ]
    else:
        want = yes_ask or 0.5
        limit = round(min(0.99, max(0.01, min(want + 0.02, avail * 0.97))), 4)
        candidates = [
            {"side": "yes", "price": limit, "label": "side_yes_limit"},
            {"side": "bid", "price": limit, "label": "side_bid"},
        ]

    count = 1
    for c in candidates:
        body = {
            "ticker": ticker,
            "client_order_id": str(uuid.uuid4()),
            "side": c["side"],
            "count": str(count),
            "price": f"{c['price']:.4f}",
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": False,
            "cancel_order_on_pause": True,
            "exchange_index": config.kalshi_exchange_index,
        }
        print("\nTRY", c["label"], json.dumps(body))
        for host in (config.kalshi_trade, kalshi_live.ALT_HOST):
            for opath in kalshi_live.ALT_ORDER_PATHS:
                try:
                    st_o, data = kalshi_live._kreq(kid, pk, "POST", opath, body, base=host)
                    print("OK", host.split("//")[-1], opath, "http", st_o)
                    print(json.dumps(data)[:500])
                    order = data.get("order") if isinstance(data.get("order"), dict) else data
                    fill = str((order or {}).get("fill_count") or "0")
                    print("fill_count", fill)
                    if fill and float(fill) > 0:
                        time.sleep(1)
                        stb2, bal2 = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/balance")
                        print("balance_after", json.dumps({k: bal2.get(k) for k in ("balance", "balance_dollars", "balance_breakdown")}))
                        return 0
                except Exception as exc:  # noqa: BLE001
                    print("ERR", host.split("//")[-1], opath, str(exc)[:220])
    print("ALL_CANDIDATES_FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
