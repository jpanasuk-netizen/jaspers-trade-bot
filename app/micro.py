"""Jev-X market microstructure extras: RSI, funding, OI, 24h change — public APIs."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}

UA = {"User-Agent": "jev-15m-kalshi-bot/1.0", "Accept": "application/json"}


def _get(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def fetch_microstructure(symbol: str = "BTC") -> dict[str, Any]:
    """CoinGecko + Binance public futures for Jev-X style market block."""
    global _CACHE
    now = time.time()
    if _CACHE.get("data") and now - float(_CACHE.get("ts") or 0) < 60:
        return dict(_CACHE["data"])

    sym = symbol.upper().replace("$", "")
    gecko_id = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}.get(sym, "bitcoin")
    out: dict[str, Any] = {
        "symbol": sym,
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "rsi_14": None,
        "funding_rate_pct": None,
        "open_interest_usd": None,
        "oi_change_pct": None,
        "sources": [],
        "errors": [],
    }

    # CoinGecko market chart / simple price
    try:
        cg = _get(
            f"https://api.coingecko.com/api/v3/coins/{gecko_id}"
            f"?localization=false&tickers=false&community_data=false&developer_data=false"
        )
        m = cg.get("market_data") or {}
        out["price"] = m.get("current_price", {}).get("usd")
        out["change_24h_pct"] = m.get("price_change_percentage_24h")
        out["volume_24h_usd"] = m.get("total_volume", {}).get("usd")
        out["sources"].append("coingecko")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"gecko:{exc}"[:120])

    # Binance spot klines for RSI
    try:
        kl = _get(
            f"https://api.binance.com/api/v3/klines?symbol={sym}USDT&interval=1m&limit=40"
        )
        closes = [float(k[4]) for k in kl]
        out["rsi_14"] = _rsi(closes, 14)
        if out["price"] is None and closes:
            out["price"] = closes[-1]
        out["sources"].append("binance_spot")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"binance_klines:{exc}"[:120])

    # Binance USDT-M futures funding + OI
    try:
        fr = _get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}USDT")
        # lastFundingRate is a fraction, e.g. 0.0001 = 0.01%
        out["funding_rate_pct"] = round(float(fr.get("lastFundingRate") or 0) * 100.0, 4)
        out["sources"].append("binance_funding")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"funding:{exc}"[:120])

    try:
        oi = _get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}USDT")
        oi_val = float(oi.get("openInterest") or 0)
        # mark price for notional
        mark = out.get("price") or 0
        out["open_interest_usd"] = round(oi_val * float(mark or 0), 2) if mark else oi_val
        out["sources"].append("binance_oi")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"oi:{exc}"[:120])

    # Coinbase ticker fallback for price
    if out["price"] is None:
        try:
            cb = _get("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
            out["price"] = float(cb.get("price") or 0) or None
            out["sources"].append("coinbase")
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"cb:{exc}"[:120])

    # Coinbase candles for RSI when Binance blocked
    if out.get("rsi_14") is None:
        try:
            cb_kl = _get(
                f"https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=60"
            )
            closes = [float(row[4]) for row in (cb_kl or [])[:60]]
            closes.reverse()
            out["rsi_14"] = _rsi(closes, 14)
            out["sources"].append("coinbase_candles")
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"cb_candles:{exc}"[:120])

    # Bybit linear perps: funding + OI (often open when Binance is 451)
    try:
        bb = _get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}USDT")
        lst = ((bb.get("result") or {}).get("list")) or []
        if lst:
            row = lst[0]
            fr = row.get("fundingRate")
            if fr not in (None, ""):
                out["funding_rate_pct"] = round(float(fr) * 100.0, 4)
            if row.get("openInterestValue"):
                out["open_interest_usd"] = float(row["openInterestValue"])
            elif row.get("openInterest") and out.get("price"):
                out["open_interest_usd"] = round(float(row["openInterest"]) * float(out["price"]), 2)
            if out.get("price") is None and row.get("lastPrice"):
                out["price"] = float(row["lastPrice"])
            out["sources"].append("bybit")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"bybit:{exc}"[:120])

    out["ts"] = now
    _CACHE = {"ts": now, "data": out}
    return dict(out)
