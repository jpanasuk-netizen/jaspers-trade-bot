"""Coinbase spot + Kalshi KXBTC15M public books. Stdlib HTTP only."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .config import config


def _get_json(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "jev-15m-kalshi-bot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cents_or_dollars(v: Any) -> float | None:
    x = _f(v)
    if x is None:
        return None
    if x > 1.5:
        return x / 100.0
    return x


def fetch_btc_spot() -> dict[str, Any]:
    """Coinbase Exchange public ticker for BTC-USD."""
    try:
        data = _get_json(config.coinbase_rest)
        price = _f(data.get("price"))
        return {
            "ok": price is not None,
            "symbol": "BTC-USD",
            "price": price,
            "bid": _f(data.get("bid")),
            "ask": _f(data.get("ask")),
            "volume_24h": _f(data.get("volume")),
            "time": data.get("time"),
            "source": "coinbase_rest",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200], "price": None, "source": "coinbase_rest"}


def _side_prices(m: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
    yb = _f(m.get("yes_bid_dollars"))
    ya = _f(m.get("yes_ask_dollars"))
    nb = _f(m.get("no_bid_dollars"))
    na = _f(m.get("no_ask_dollars"))
    if yb is None:
        yb = _cents_or_dollars(m.get("yes_bid"))
    if ya is None:
        ya = _cents_or_dollars(m.get("yes_ask"))
    if nb is None:
        nb = _cents_or_dollars(m.get("no_bid"))
    if na is None:
        na = _cents_or_dollars(m.get("no_ask"))
    return yb, ya, nb, na


def _et_zone():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001
        import datetime as dt

        # crude EST fallback if zoneinfo data is missing
        return dt.timezone(dt.timedelta(hours=-5))


def _parse_close_epoch(raw: Any) -> float | None:
    if not raw:
        return None
    import datetime as dt

    s = str(raw).strip().replace("Z", "+00:00")
    try:
        close_dt = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if close_dt.tzinfo is None:
        close_dt = close_dt.replace(tzinfo=dt.timezone.utc)
    return close_dt.timestamp()


def refresh_seconds_left(market: dict[str, Any] | None) -> dict[str, Any]:
    """Keep seconds_left live off close_epoch — don't wait for the next HTTP pull."""
    if not market:
        return {}
    close_epoch = market.get("close_epoch")
    if close_epoch is None:
        close_epoch = _parse_close_epoch(market.get("close_time") or market.get("expiration_time"))
        if close_epoch is not None:
            market["close_epoch"] = close_epoch
            if market.get("open_epoch") is None:
                market["open_epoch"] = close_epoch - 15 * 60
    if close_epoch is not None:
        market["seconds_left"] = max(0.0, float(close_epoch) - time.time())
    return market


def _window_meta(ticker: str) -> dict[str, Any]:
    """Parse KXBTC15M tickers into window open/close.

    Tickers look like KXBTC15M-26SEP200845-45. The YYMMMDDHHMM stamp is
    America/New_York close time (not UTC open). Prefer API close_time when
    present — this is only a fallback.
    """
    info = {
        "ticker": ticker,
        "window_id": ticker,
        "open_epoch": None,
        "close_epoch": None,
        "seconds_left": None,
        "open_of_window": None,
    }
    if not ticker or "-" not in ticker:
        return info
    parts = ticker.split("-")
    months = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    }
    import datetime as dt

    et = _et_zone()
    for part in parts:
        p = part.upper()
        if len(p) >= 11 and p[2:5] in months and p[5:7].isdigit() and p[7:11].isdigit():
            try:
                yy = int(p[0:2])
                year = 2000 + yy
                month = months[p[2:5]]
                day = int(p[5:7])
                hour = int(p[7:9])
                minute = int(p[9:11])
                # Stamp is Eastern close of the 15m window.
                close_dt = dt.datetime(year, month, day, hour, minute, tzinfo=et)
                open_dt = close_dt - dt.timedelta(minutes=15)
                now = dt.datetime.now(dt.timezone.utc)
                info["open_epoch"] = open_dt.timestamp()
                info["close_epoch"] = close_dt.timestamp()
                info["seconds_left"] = max(0.0, close_dt.timestamp() - now.timestamp())
                info["window_id"] = open_dt.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
            except (ValueError, OverflowError):
                pass
            break
    return info


def _normalize_market(m: dict[str, Any], series: str) -> dict[str, Any]:
    ticker = m.get("ticker") or "?"
    yb, ya, nb, na = _side_prices(m)
    mid_yes = None
    if yb is not None and ya is not None:
        mid_yes = (yb + ya) / 2.0
    elif ya is not None:
        mid_yes = ya
    elif yb is not None:
        mid_yes = yb

    status = (m.get("status") or "").lower()
    if status in {"closed", "determined", "settled", "finalized"}:
        settled = True
    else:
        settled = False

    strike = _f(m.get("yes_sub_title") or m.get("strike"))
    # Some books embed open price in subtitle/description
    open_px = _f(m.get("open_price") or m.get("yes_sub_title"))
    if open_px is None:
        # try "above $X" patterns later via market text
        text = " ".join(
            str(m.get(k) or "")
            for k in ("yes_sub_title", "no_sub_title", "title", "yes_title", "event_ticker")
        )
        for token in text.replace(",", "").split():
            token = token.strip("$")
            try:
                val = float(token)
            except ValueError:
                continue
            if 1000 < val < 1_000_000:
                open_px = val
                break

    win = _window_meta(ticker)
    close_raw = m.get("close_time") or m.get("expiration_time")
    close_epoch = _parse_close_epoch(close_raw)
    if close_epoch is not None:
        win["close_epoch"] = close_epoch
        win["open_epoch"] = close_epoch - 15 * 60
        win["seconds_left"] = max(0.0, close_epoch - time.time())
    volume = m.get("volume_fp")
    if volume is None:
        volume = m.get("volume")

    out = {
        "series": series,
        "ticker": ticker,
        "status": m.get("status") or "",
        "settled": settled,
        "yes_bid": yb,
        "yes_ask": ya,
        "no_bid": nb,
        "no_ask": na,
        "yes_mid": mid_yes,
        "volume": _f(volume),
        "strike": strike,
        "open_of_window": open_px,
        "window_id": win["window_id"],
        "open_epoch": win["open_epoch"],
        "close_epoch": win["close_epoch"],
        "seconds_left": win["seconds_left"],
        "close_time": close_raw,
        "result": m.get("result") or "",
        "raw_status": m.get("status"),
    }
    return refresh_seconds_left(out)


def fetch_kalshi_btc_book() -> dict[str, Any]:
    """Open (and near-open) KXBTC15M markets from public Kalshi API (no auth)."""
    markets: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []
    # `status=open` briefly empties between 15m rolls — also try the series unfiltered.
    urls = [
        f"{config.kalshi_public}/markets?series_ticker={config.series_ticker}&status=open&limit=25",
        f"{config.kalshi_public}/markets?series_ticker={config.series_ticker}&limit=25",
    ]
    try:
        for url in urls:
            try:
                data = _get_json(url)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc)[:120])
                continue
            for m in data.get("markets") or []:
                st = (m.get("status") or "").lower()
                if st in {"closed", "determined", "settled", "finalized"}:
                    continue
                norm = _normalize_market(m, config.series_ticker)
                if norm["ticker"] in seen:
                    continue
                seen.add(norm["ticker"])
                markets.append(norm)
            if markets:
                break
        from .fast_feed import _pick_active

        active = _pick_active(markets) if markets else None
        return {
            "ok": True,
            "series": config.series_ticker,
            "count": len(markets),
            "active": active,
            "markets": markets[:8],
            "fetched_at": time.time(),
            "source": "kalshi_public",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc)[:200],
            "series": config.series_ticker,
            "count": 0,
            "active": None,
            "markets": [],
            "source": "kalshi_public",
        }


def snapshot() -> dict[str, Any]:
    """Fast-ahead snapshot: race Kalshi hosts + BTC spot; fall back to serial REST."""
    try:
        from .fast_feed import fast_snapshot, start_fast_feed

        # kick background racer once; return latest cache immediately
        snap = fast_snapshot()
        if snap.get("spot") or snap.get("kalshi"):
            spot = snap.get("spot") or {}
            book = snap.get("kalshi") or {}
            if not book.get("active") and not snap.get("window"):
                # rare empty race — serial fallback for this tick
                snap = None
            else:
                out = {
                    "ts": snap.get("ts") or time.time(),
                    "spot": spot,
                    "kalshi": book,
                    "window": snap.get("window") or {},
                    "fast_feed": {
                        "mode": snap.get("mode"),
                        "latency": snap.get("latency"),
                        "fair_yes": snap.get("fair_yes"),
                        "seq": snap.get("seq"),
                        "edge_vs_book": (snap.get("window") or {}).get("edge_vs_book"),
                        "errors": snap.get("errors"),
                        "source": "fast_feed",
                    },
                }
                return out
        # fall through to serial
    except Exception:  # noqa: BLE001
        snap = None

    spot = fetch_btc_spot()
    book = fetch_kalshi_btc_book()
    active = book.get("active") or {}
    open_px = active.get("open_of_window")
    price = spot.get("price")
    delta = None
    delta_pct = None
    if price is not None and open_px:
        delta = price - open_px
        delta_pct = (delta / open_px) * 100.0 if open_px else None
        active["open_of_window"] = open_px
        active["delta_from_open"] = delta
        active["delta_pct"] = delta_pct
    return {
        "ts": time.time(),
        "spot": spot,
        "kalshi": book,
        "window": {
            "ticker": active.get("ticker"),
            "window_id": active.get("window_id"),
            "seconds_left": active.get("seconds_left"),
            "open_of_window": open_px,
            "delta_from_open": delta,
            "delta_pct": delta_pct,
            "yes_ask": active.get("yes_ask"),
            "no_ask": active.get("no_ask"),
            "yes_bid": active.get("yes_bid"),
            "no_bid": active.get("no_bid"),
            "yes_mid": active.get("yes_mid"),
        },
        "fast_feed": {"source": "serial_fallback"},
    }
