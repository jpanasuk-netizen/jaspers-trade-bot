"""Live Kalshi V2 order probe — YES-book bid/ask, auto-route exchange_index=-1."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import kalshi_live  # noqa: E402

PATH = "/trade-api/v2/portfolio/events/orders"


def try_order(kid, pk, ticker, side, price, count="1", ex=-1, tif="immediate_or_cancel"):
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": side,  # bid=buy YES, ask=sell YES (=buy NO)
        "count": count if "." in count else f"{float(count):.2f}",
        "price": f"{float(price):.4f}",
        "time_in_force": tif,
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": True,
        "reduce_only": False,
        "exchange_index": ex,
    }
    print("\nPOST", json.dumps(body))
    for host in ("https://api.elections.kalshi.com", "https://external-api.kalshi.com"):
        try:
            st, data = kalshi_live._kreq(kid, pk, "POST", PATH, body, base=host)
            print("HTTP", st, host.split("//")[-1])
            print(json.dumps(data)[:600])
            order = data.get("order") if isinstance(data.get("order"), dict) else data
            fill = float(order.get("fill_count") or 0) if isinstance(order, dict) else 0
            print("fill_count", order.get("fill_count") if isinstance(order, dict) else None)
            return fill > 0, data
        except Exception as exc:  # noqa: BLE001
            print("ERR", host.split("//")[-1], str(exc)[:280])
    return False, None


def main() -> int:
    kid, pk = kalshi_live.load_creds()
    _st, mkts = kalshi_live._kreq(
        kid, pk, "GET",
        "/trade-api/v2/markets?limit=5&series_ticker=KXBTC15M&status=open",
    )
    markets = mkts.get("markets") or []
    if not markets:
        print("no open market")
        return 2
    m = markets[0]
    ticker = m["ticker"]
    yes_bid = float(m.get("yes_bid_dollars") or m.get("yes_bid") or 0)
    yes_ask = float(m.get("yes_ask_dollars") or m.get("yes_ask") or 0)
    no_ask = float(m.get("no_ask_dollars") or m.get("no_ask") or 0)
    print("ticker", ticker, "yes_bid", yes_bid, "yes_ask", yes_ask, "no_ask", no_ask)

    _stb, bal = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/balance")
    print("balance", bal.get("balance_dollars"), bal.get("balance_breakdown"))

    side = (sys.argv[1] if len(sys.argv) > 1 else "NO").upper()
    attempts = []
    if side == "NO":
        # sell YES at/near yes_bid → economically long NO
        px = round(max(0.01, yes_bid), 4) if yes_bid else round(max(0.01, 1.0 - no_ask), 4)
        attempts = [
            ("ask", px, -1),
            ("ask", round(px + 0.01, 4), -1),
            ("ask", px, 0),
            ("ask", px, None),
        ]
    else:
        px = round(min(0.99, yes_ask), 4) if yes_ask else 0.5
        attempts = [
            ("bid", px, -1),
            ("bid", round(min(0.99, px + 0.02), 4), -1),
            ("bid", px, 0),
        ]

    for side_ba, price, ex in attempts:
        if ex is None:
            # omit exchange_index — auto route
            body_ex = -1
            # try without by using -1 first; then a second call without field via custom
            filled, data = try_order(kid, pk, ticker, side_ba, price, "1", ex=-1)
        else:
            filled, data = try_order(kid, pk, ticker, side_ba, price, "1", ex=ex)
        if filled:
            time_sleep_and_bal(kid, pk)
            return 0

    # last resort: omit exchange_index key entirely
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": "ask" if side == "NO" else "bid",
        "count": "1.00",
        "price": f"{(yes_bid or 0.2):.4f}" if side == "NO" else f"{(yes_ask or 0.5):.4f}",
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": True,
    }
    print("\nPOST no-exchange-index", json.dumps(body))
    for host in ("https://api.elections.kalshi.com", "https://external-api.kalshi.com"):
        try:
            st, data = kalshi_live._kreq(kid, pk, "POST", PATH, body, base=host)
            print("HTTP", st, json.dumps(data)[:500])
            order = data.get("order") if isinstance(data.get("order"), dict) else data
            if isinstance(order, dict) and float(order.get("fill_count") or 0) > 0:
                time_sleep_and_bal(kid, pk)
                return 0
        except Exception as exc:  # noqa: BLE001
            print("ERR", host, str(exc)[:280])
    return 1


def time_sleep_and_bal(kid, pk):
    import time
    time.sleep(1.5)
    _st, bal = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/balance")
    print("BALANCE_AFTER", json.dumps({k: bal.get(k) for k in ("balance", "balance_dollars", "balance_breakdown")}))
    try:
        _st2, pos = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/positions?limit=10")
        print("POSITIONS", json.dumps(pos)[:400])
    except Exception as e:
        print("pos_err", str(e)[:160])


if __name__ == "__main__":
    raise SystemExit(main())
