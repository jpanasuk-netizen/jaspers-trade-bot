"""Fast-ahead multi-source market feed for Kalshi KXBTC15M.

Race every public path; keep the fastest live quoted book + BTC spot.
Hot path: once ticker is known, poll orderbook + trades directly (~50-70ms).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .config import config
from .market import _normalize_market, _window_meta, refresh_seconds_left

UA = {
    "User-Agent": "jev-15m-fast/2.0",
    "Accept": "application/json",
    "Connection": "keep-alive",
}

KALSHI_HOSTS = [
    "https://api.elections.kalshi.com/trade-api/v2",
]

# Fastest-first from this network — keep the race tight for latency.
SPOT_SOURCES: list[tuple[str, str]] = [
    ("coinbase_ex", "https://api.exchange.coinbase.com/products/BTC-USD/ticker"),
    ("kraken", "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"),
    ("coinbase_v2", "https://api.coinbase.com/v2/prices/BTC-USD/spot"),
    ("bitstamp", "https://www.bitstamp.net/api/v2/ticker/btcusd/"),
    ("gemini", "https://api.gemini.com/v1/pubticker/btcusd"),
    ("okx", "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT"),
]

ELECTIONS = "https://api.elections.kalshi.com/trade-api/v2"

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "ts": 0.0,
    "spot": None,
    "book": None,
    "fair_yes": None,
    "latency": {},
    "seq": 0,
    "errors": [],
    "ws_spot": None,
    "mode": "rest-race",
}
_STOP = threading.Event()
_THREADS: list[threading.Thread] = []
_OPENER: Any = None


def _get(url: str, timeout: float = 1.2) -> tuple[float, Any]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers=UA)
    # shared opener for TCP reuse across polls
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener()
    with _OPENER.open(req, timeout=timeout) as resp:
        raw = resp.read()
    dt = (time.perf_counter() - t0) * 1000.0
    return dt, json.loads(raw.decode("utf-8"))


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _kalshi_px(v: Any) -> float | None:
    x = _f(v)
    if x is None:
        return None
    return x / 100.0 if x > 1.5 else x


def _parse_target_price(*texts: Any) -> float | None:
    for t in texts:
        if not t:
            continue
        if isinstance(t, (int, float)) and float(t) > 1000:
            return float(t)
        m = re.search(r"\$\s*([0-9][0-9,]*\.?[0-9]*)", str(t))
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _parse_spot(name: str, data: Any) -> float | None:
    try:
        if name == "binance_spot":
            bid, ask = _f(data.get("bidPrice")), _f(data.get("askPrice"))
            if bid and ask:
                return (bid + ask) / 2.0
            return bid or ask
        if name in {"binance_price", "binance_us"}:
            return _f(data.get("price"))
        if name == "coinbase_v2":
            return _f((data.get("data") or {}).get("amount"))
        if name == "coinbase_ex":
            bid, ask = _f(data.get("bid")), _f(data.get("ask"))
            if bid and ask:
                return (bid + ask) / 2.0
            return _f(data.get("price"))
        if name == "okx":
            rows = data.get("data") or []
            if rows:
                return _f(rows[0].get("last"))
        if name == "bybit":
            rows = ((data.get("result") or {}).get("list")) or []
            if rows:
                return _f(rows[0].get("lastPrice"))
        if name == "kraken":
            for v in (data.get("result") or {}).values():
                if isinstance(v, dict) and v.get("c"):
                    return _f(v["c"][0])
        if name == "gemini":
            return _f(data.get("last") or data.get("ask"))
        if name == "bitstamp":
            return _f(data.get("last") or data.get("ask"))
    except Exception:  # noqa: BLE001
        return None
    return None


def _fetch_spot_race() -> dict[str, Any]:
    best: dict[str, Any] | None = None
    lat: dict[str, float] = {}
    errors: list[str] = []

    def work(item: tuple[str, str]) -> tuple[str, float, float | None, str | None]:
        name, url = item
        try:
            dt, data = _get(url, timeout=2.0)
            px = _parse_spot(name, data)
            return name, dt, px, None
        except Exception as exc:  # noqa: BLE001
            return name, 0.0, None, f"{name}:{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=len(SPOT_SOURCES)) as ex:
        futs = [ex.submit(work, it) for it in SPOT_SOURCES]
        for fut in as_completed(futs):
            name, dt, px, err = fut.result()
            if err:
                errors.append(err)
                continue
            lat[name] = round(dt, 1)
            if px and px > 1000:
                cand = {
                    "ok": True,
                    "price": px,
                    "source": name,
                    "latency_ms": round(dt, 1),
                    "ts": time.time(),
                }
                if best is None or (cand["latency_ms"] or 999) < (best.get("latency_ms") or 999):
                    best = cand
    if best is None:
        return {"ok": False, "price": None, "errors": errors[:4], "latency_ms": None}
    best["all_latency_ms"] = lat
    best["errors"] = errors[:4]
    return best


MIN_TRADE_SECS = 8.0  # match risk-gate data_freshness
MAX_CURRENT_SECS = 16 * 60.0  # current 15m + 1m slack


def _has_px(m: dict[str, Any]) -> bool:
    return any(
        v is not None and float(v) > 0.0
        for v in (m.get("yes_ask"), m.get("no_ask"), m.get("yes_bid"), m.get("no_bid"))
    )


def _rank_market(m: dict[str, Any]) -> tuple:
    refresh_seconds_left(m)
    has_px = _has_px(m)
    secs = m.get("seconds_left")
    secs_f = float(secs) if secs is not None else -1.0
    settled = bool(m.get("settled")) or str(m.get("status") or "").lower() in {
        "closed", "determined", "settled", "finalized",
    }
    if settled or 0 <= secs_f <= MIN_TRADE_SECS:
        time_rank = 3  # dead / last seconds — do not trade
    elif MIN_TRADE_SECS < secs_f <= MAX_CURRENT_SECS:
        time_rank = 0  # live current window
    elif secs_f > MAX_CURRENT_SECS:
        time_rank = 1  # next window
    else:
        time_rank = 2
    empty = 0 if has_px else 1
    # among live windows, prefer more time remaining (not the dying print)
    closeness = -secs_f if time_rank == 0 else (secs_f if secs_f >= 0 else 1e9)
    return (time_rank, empty, closeness)


def _pick_active(markets: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not markets:
        return None
    ranked = sorted(markets, key=_rank_market)
    live = [m for m in ranked if _rank_market(m)[0] == 0]
    if live:
        return live[0]
    upcoming = [m for m in ranked if _rank_market(m)[0] == 1]
    if upcoming:
        return upcoming[0]
    return ranked[0]


def _fetch_kalshi_book_race(series: str | None = None) -> dict[str, Any]:
    series = series or config.series_ticker
    errors: list[str] = []
    best: dict[str, Any] | None = None
    paths = [
        f"/markets?series_ticker={series}&status=open&limit=10",
    ]
    jobs = [h + p for h in KALSHI_HOSTS for p in paths]

    def work(url: str) -> tuple[str, float, dict[str, Any] | None, str | None]:
        try:
            dt, data = _get(url, timeout=2.0)
            return url, dt, data, None
        except Exception as exc:  # noqa: BLE001
            return url, 0.0, None, f"{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as ex:
        futs = [ex.submit(work, u) for u in jobs]
        for fut in as_completed(futs):
            url, dt, data, err = fut.result()
            if err:
                errors.append(err)
                continue
            markets_raw = (data or {}).get("markets") or []
            if not markets_raw:
                continue
            markets: list[dict[str, Any]] = []
            seen: set[str] = set()
            for m in markets_raw:
                st = (m.get("status") or "").lower()
                if st in {"closed", "determined", "settled", "finalized"}:
                    continue
                norm = _normalize_market(m, series)
                if norm.get("open_of_window") is None:
                    cs = m.get("custom_strike") or {}
                    norm["open_of_window"] = _parse_target_price(
                        cs.get("target_price") if isinstance(cs, dict) else None,
                        cs.get("strike_price") if isinstance(cs, dict) else None,
                        m.get("strike"),
                        m.get("yes_sub_title"),
                        m.get("title"),
                    )
                if norm["ticker"] in seen:
                    continue
                seen.add(norm["ticker"])
                markets.append(norm)
            if not markets:
                continue
            active = _pick_active(markets)
            cand = {
                "ok": True,
                "series": series,
                "count": len(markets),
                "active": active,
                "markets": markets[:8],
                "source_url": url,
                "latency_ms": round(dt, 1),
                "fetched_at": time.time(),
                "source": "kalshi_race",
            }
            score = cand["latency_ms"] or 999
            if active:
                r = _rank_market(active)
                if r[0] == 1:
                    score += 800
                if r[1] != 0:
                    score += 400
            if best is None or score < best.get("_score", 9999):
                best = cand
                best["_score"] = score

    if best is None:
        return {
            "ok": False,
            "error": "; ".join(errors[:3]) or "no kalshi data",
            "series": series,
            "count": 0,
            "active": None,
            "markets": [],
            "source": "kalshi_race",
        }
    best.pop("_score", None)
    return best


def _top_of_book_from_orderbook(ob: dict[str, Any]) -> dict[str, Any]:
    fp = ob.get("orderbook_fp") or ob.get("orderbook") or {}

    def best_ask(key: str) -> float | None:
        rows = fp.get(key) or []
        prices = []
        for row in rows:
            if not row:
                continue
            try:
                prices.append(float(row[0]))
            except (TypeError, ValueError, IndexError):
                continue
        return min(prices) if prices else None

    yes_ask = best_ask("yes_dollars")
    no_ask = best_ask("no_dollars")
    out: dict[str, Any] = {
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "yes_bid": (1.0 - no_ask) if no_ask is not None else None,
        "no_bid": (1.0 - yes_ask) if yes_ask is not None else None,
    }
    if out["yes_ask"] is not None and out["yes_bid"] is not None:
        out["yes_mid"] = (out["yes_ask"] + out["yes_bid"]) / 2.0
    elif out["yes_ask"] is not None:
        out["yes_mid"] = out["yes_ask"]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def _hot_poll_ticker(ticker: str) -> dict[str, Any]:
    out: dict[str, Any] = {"ticker": ticker}
    t0 = time.perf_counter()
    try:
        dt, ob = _get(f"{ELECTIONS}/markets/{ticker}/orderbook", timeout=1.5)
        out["orderbook_latency_ms"] = round(dt, 1)
        out["book"] = _top_of_book_from_orderbook(ob)
    except Exception as exc:  # noqa: BLE001
        out["orderbook_error"] = str(exc)[:120]
    try:
        dt2, tr = _get(f"{ELECTIONS}/markets/trades?limit=5&ticker={ticker}", timeout=1.5)
        out["trades_latency_ms"] = round(dt2, 1)
        rows = tr.get("trades") or []
        out["trades"] = [
            {
                "ts": r.get("created_time"),
                "yes": _kalshi_px(r.get("yes_price_dollars") or r.get("yes_price")),
                "no": _kalshi_px(r.get("no_price_dollars") or r.get("no_price")),
                "count": r.get("count_fp") or r.get("count"),
            }
            for r in rows[:5]
        ]
        if out["trades"]:
            out["last_print"] = out["trades"][0]
    except Exception as exc:  # noqa: BLE001
        out["trades_error"] = str(exc)[:120]
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return out


def _fair_yes_prob(price: float | None, open_px: float | None, seconds_left: float | None) -> float | None:
    if price is None or open_px is None or not open_px:
        return None
    import math

    secs = max(5.0, float(seconds_left or 60.0))
    sigma = 0.0005 * math.sqrt(secs / 900.0) * price
    if sigma <= 0:
        return 0.5
    z = (price - open_px) / sigma
    p = 1.0 / (1.0 + math.exp(-1.7 * z))
    return max(0.01, min(0.99, p))


def _try_ws_spot() -> None:
    """Coinbase + Binance WS tickers — sub-second spot that leads Kalshi."""
    try:
        import asyncio

        import websockets  # type: ignore
    except Exception:  # noqa: BLE001
        print("[ws] websockets not installed — REST race only", flush=True)
        return

    async def coinbase_ws() -> None:
        uri = "wss://ws-feed.exchange.coinbase.com"
        sub = {
            "type": "subscribe",
            "product_ids": ["BTC-USD"],
            "channels": ["ticker"],
        }
        while not _STOP.is_set():
            try:
                async with websockets.connect(uri, ping_interval=20) as ws:
                    await ws.send(json.dumps(sub))
                    with _LOCK:
                        _CACHE["mode"] = "ws+rest-race"
                    async for msg in ws:
                        if _STOP.is_set():
                            break
                        try:
                            d = json.loads(msg)
                            if d.get("type") != "ticker":
                                continue
                            price = float(d.get("price") or 0)
                            bid = float(d.get("best_bid") or 0) or None
                            ask = float(d.get("best_ask") or 0) or None
                            if price <= 0:
                                continue
                            with _LOCK:
                                _CACHE["ws_spot"] = {
                                    "price": price,
                                    "bid": bid,
                                    "ask": ask,
                                    "source": "coinbase_ws",
                                    "ts": time.time(),
                                    "sequence": d.get("sequence"),
                                }
                        except Exception:  # noqa: BLE001
                            continue
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.4)

    async def binance_ws() -> None:
        uri = "wss://stream.binance.com:9443/ws/btcusdt@bookTicker"
        while not _STOP.is_set():
            try:
                async with websockets.connect(uri, ping_interval=15) as ws:
                    async for msg in ws:
                        if _STOP.is_set():
                            break
                        try:
                            d = json.loads(msg)
                            bid, ask = float(d["b"]), float(d["a"])
                            with _LOCK:
                                cur = _CACHE.get("ws_spot") or {}
                                # only override if newer/faster source absent
                                if cur.get("source") != "coinbase_ws" or time.time() - float(cur.get("ts") or 0) > 1.5:
                                    _CACHE["ws_spot"] = {
                                        "price": (bid + ask) / 2.0,
                                        "bid": bid,
                                        "ask": ask,
                                        "source": "binance_ws",
                                        "ts": time.time(),
                                    }
                        except Exception:  # noqa: BLE001
                            continue
            except Exception:  # noqa: BLE001
                await asyncio.sleep(1.0)

    def runner() -> None:
        async def both() -> None:
            await asyncio.gather(coinbase_ws(), binance_ws(), return_exceptions=True)

        try:
            asyncio.run(both())
        except Exception:  # noqa: BLE001
            return

    t = threading.Thread(target=runner, name="fcc-ws-spot", daemon=True)
    t.start()
    _THREADS.append(t)
    print("[ws] coinbase + binance ticker loops started", flush=True)


def start_fast_feed(poll_sec: float = 0.25) -> None:
    if any(t.name == "fcc-fast-feed" and t.is_alive() for t in _THREADS):
        return
    _STOP.clear()
    _try_ws_spot()

    def loop() -> None:
        last_ticker = None
        while not _STOP.is_set():
            try:
                t0 = time.perf_counter()
                hot = None
                if last_ticker:
                    try:
                        hot = _hot_poll_ticker(last_ticker)
                    except Exception:  # noqa: BLE001
                        hot = None
                with ThreadPoolExecutor(max_workers=2) as ex:
                    spot = ex.submit(_fetch_spot_race).result()
                    book = ex.submit(_fetch_kalshi_book_race).result() or {}
                wall = (time.perf_counter() - t0) * 1000.0
                active = dict(book.get("active") or {})
                if hot and hot.get("book") and hot.get("ticker") == active.get("ticker"):
                    hb = hot["book"]
                    list_mid = active.get("yes_mid")
                    for k, v in hb.items():
                        if v is None:
                            continue
                        try:
                            fv = float(v)
                        except (TypeError, ValueError):
                            continue
                        # only accept sane contract prices
                        if k in {"yes_ask", "no_ask", "yes_bid", "no_bid", "yes_mid"}:
                            if not (0.0 < fv < 1.0):
                                continue
                            # don't replace a good list quote with a wild orderbook edge
                            if list_mid is not None and k == "yes_mid" and abs(fv - float(list_mid)) > 0.25:
                                continue
                            if list_mid is not None and k in {"yes_ask", "yes_bid"} and abs(fv - float(list_mid)) > 0.35:
                                continue
                        active[k] = fv
                    book = dict(book)
                    book["active"] = active
                    book["hot"] = hot
                if active.get("ticker"):
                    last_ticker = active.get("ticker")

                with _LOCK:
                    ws = _CACHE.get("ws_spot")
                if ws and time.time() - float(ws.get("ts") or 0) < 2.0:
                    spot = dict(spot or {})
                    spot["price"] = ws["price"]
                    spot["bid"] = ws.get("bid")
                    spot["ask"] = ws.get("ask")
                    spot["source"] = ws.get("source") or "ws"
                    spot["latency_ms"] = 0.0  # already in-process
                    spot["ws"] = True

                open_px = active.get("open_of_window")
                price = (spot or {}).get("price")
                fair = _fair_yes_prob(price, open_px, active.get("seconds_left"))
                if price is not None and open_px:
                    active["delta_from_open"] = price - open_px
                    active["delta_pct"] = ((price - open_px) / open_px) * 100.0

                with _LOCK:
                    _CACHE["ts"] = time.time()
                    _CACHE["spot"] = spot
                    _CACHE["book"] = book
                    _CACHE["fair_yes"] = fair
                    _CACHE["seq"] = int(_CACHE.get("seq") or 0) + 1
                    _CACHE["latency"] = {
                        "wall_ms": round(wall, 1),
                        "spot_ms": (spot or {}).get("latency_ms"),
                        "spot_source": (spot or {}).get("source"),
                        "book_ms": book.get("latency_ms"),
                        "hot_ms": (hot or {}).get("latency_ms"),
                        "last_print": (hot or {}).get("last_print"),
                        "ticker": last_ticker,
                        "spot_all": (spot or {}).get("all_latency_ms") or {},
                    }
                    errs = list((spot or {}).get("errors") or [])
                    if book.get("error"):
                        errs.append(str(book.get("error"))[:120])
                    _CACHE["errors"] = errs
            except Exception as exc:  # noqa: BLE001
                with _LOCK:
                    _CACHE["errors"] = [f"loop:{type(exc).__name__}:{exc}"[:160]]
            time.sleep(max(0.2, poll_sec))

    t = threading.Thread(target=loop, name="fcc-fast-feed", daemon=True)
    t.start()
    _THREADS.append(t)


def stop_fast_feed() -> None:
    _STOP.set()


def fast_snapshot() -> dict[str, Any]:
    with _LOCK:
        have = _CACHE.get("spot") is not None or _CACHE.get("book") is not None
        seq = _CACHE.get("seq") or 0
    if not have or seq == 0:
        spot = _fetch_spot_race()
        book = _fetch_kalshi_book_race()
        active = dict(book.get("active") or {})
        open_px = active.get("open_of_window")
        price = (spot or {}).get("price")
        fair = _fair_yes_prob(price, open_px, active.get("seconds_left"))
        if price is not None and open_px:
            active["delta_from_open"] = price - open_px
            active["delta_pct"] = ((price - open_px) / open_px) * 100.0
            book = dict(book)
            book["active"] = active
        with _LOCK:
            _CACHE.update(
                {
                    "ts": time.time(),
                    "spot": spot,
                    "book": book,
                    "fair_yes": fair,
                    "seq": 1,
                    "latency": {
                        "spot_ms": (spot or {}).get("latency_ms"),
                        "spot_source": (spot or {}).get("source"),
                        "book_ms": book.get("latency_ms"),
                    },
                }
            )
        start_fast_feed()
    with _LOCK:
        snap = {
            "ts": _CACHE.get("ts"),
            "spot": _CACHE.get("spot"),
            "kalshi": _CACHE.get("book"),
            "fair_yes": _CACHE.get("fair_yes"),
            "latency": _CACHE.get("latency"),
            "seq": _CACHE.get("seq"),
            "errors": _CACHE.get("errors") or [],
            "mode": _CACHE.get("mode") or "rest-race",
            "source": "fast_feed",
        }
    book = snap.get("kalshi") or {}
    active = refresh_seconds_left(dict(book.get("active") or {}))
    if book.get("active") is not None:
        book = dict(book)
        book["active"] = active
        snap["kalshi"] = book
    spot = snap.get("spot") or {}
    price = spot.get("price")
    open_px = active.get("open_of_window")
    delta = delta_pct = None
    if price is not None and open_px:
        delta = price - open_px
        delta_pct = (delta / open_px) * 100.0
    win = _window_meta(active.get("ticker") or "")
    snap["window"] = {
        "ticker": active.get("ticker"),
        "window_id": active.get("window_id") or win.get("window_id"),
        "seconds_left": active.get("seconds_left"),
        "open_of_window": open_px,
        "delta_from_open": delta,
        "delta_pct": delta_pct,
        "yes_ask": active.get("yes_ask"),
        "no_ask": active.get("no_ask"),
        "yes_bid": active.get("yes_bid"),
        "no_bid": active.get("no_bid"),
        "yes_mid": active.get("yes_mid"),
        "fair_yes": snap.get("fair_yes"),
        "edge_vs_book": (
            None
            if snap.get("fair_yes") is None or active.get("yes_mid") is None
            else round(float(snap["fair_yes"]) - float(active.get("yes_mid") or 0.5), 4)
        ),
        "last_print": (snap.get("latency") or {}).get("last_print"),
    }
    return snap
