"""Read-only BTC lean from the public AI-Trader signal feed.

HKUDS/AI-Trader (https://github.com/HKUDS/AI-Trader) is a social signal
board. This desk does not register, publish our fills, or copy anyone's
orders. A fresh crowd of distinct agents buying or selling BTC is one
panel vote. A split crowd, a copied echo, or a stale print abstains.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

FEED = "https://ai4trade.ai/api/signals/feed?symbol=BTC&limit=40&message_type=operation"
MAX_AGE_SEC = 45 * 60
MIN_AGENTS = 3
_CACHE: dict[str, Any] = {"ts": 0.0, "read": None}


def lean_from_signals(signals: list[dict[str, Any]], now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    seen: dict[str, str] = {}
    for row in signals:
        if str(row.get("symbol") or "").upper() != "BTC":
            continue
        content = str(row.get("content") or "")
        if content.startswith("[Copied from"):
            continue
        side = str(row.get("side") or "").lower()
        if side in {"buy", "long"}:
            vote = "YES"
        elif side in {"sell", "short"}:
            vote = "NO"
        else:
            continue
        stamp = row.get("timestamp")
        try:
            age = now - float(stamp)
        except (TypeError, ValueError):
            age = 0.0
        if age > MAX_AGE_SEC:
            continue
        agent = str(row.get("agent_id") or row.get("agent_name") or "")
        if not agent or agent in seen:
            continue
        seen[agent] = vote
    buys = sum(1 for v in seen.values() if v == "YES")
    sells = sum(1 for v in seen.values() if v == "NO")
    total = buys + sells
    lean = "SKIP"
    # Need a real crowd, not a 2-1 split.
    if total >= MIN_AGENTS and buys >= sells + 2:
        lean = "YES"
    elif total >= MIN_AGENTS and sells >= buys + 2:
        lean = "NO"
    return {
        "lean": lean,
        "buys": buys,
        "sells": sells,
        "agents": total,
        "source": "HKUDS/AI-Trader",
        "note": "read-only crowd vote; not a copied order",
    }


def btc_crowd(force: bool = False) -> dict[str, Any]:
    now = time.time()
    cached = _CACHE.get("read")
    if not force and isinstance(cached, dict) and now - float(_CACHE.get("ts") or 0) < 45:
        return cached
    try:
        req = urllib.request.Request(FEED, headers={"Accept": "application/json", "User-Agent": "jev-15m-kalshi-bot"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            payload = json.loads(resp.read().decode() or "{}")
        signals = payload.get("signals") if isinstance(payload, dict) else []
        read = lean_from_signals(signals if isinstance(signals, list) else [], now)
    except Exception as exc:  # noqa: BLE001
        read = {"lean": "SKIP", "buys": 0, "sells": 0, "agents": 0, "error": str(exc)[:160], "source": "HKUDS/AI-Trader"}
    _CACHE["ts"] = now
    _CACHE["read"] = read
    return read
