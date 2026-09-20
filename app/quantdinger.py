"""QuantDinger + BTC research bridge for 15m Kalshi decisions.

QuantDinger (OpenByte AI Trading OS) is pointed at Bitcoin.
This module:
  1. Probes the local QuantDinger API when it is up (WSL Docker).
  2. Always computes a local BTC research pack (trend, funding, book edge)
     so 15m decisions work even if QuantDinger is still booting.
  3. Returns typed signals the judge / HUD can consume — not raw trade authority.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .config import config
from .fast_feed import fast_snapshot

UA = {"User-Agent": "jev-15m-quantdinger/1.0", "Accept": "application/json"}

_CACHE: dict[str, Any] = {"ts": 0.0, "pack": None}
_PROBE_FAIL_UNTIL = 0.0


def _get(url: str, timeout: float = 0.35) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_quantdinger() -> dict[str, Any]:
    """Single fast health check. Failed probes cache-down for 20s so we never stall."""
    global _PROBE_FAIL_UNTIL
    base = (config.quantdinger_base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "configured": False, "error": "QUANTDINGER_BASE_URL not set"}
    now = time.time()
    if now < _PROBE_FAIL_UNTIL:
        return {
            "ok": False,
            "configured": True,
            "base_url": base,
            "symbol": config.quantdinger_symbol,
            "error": "cached-down",
            "checked_at": now,
        }
    out: dict[str, Any] = {
        "ok": False,
        "configured": True,
        "base_url": base,
        "symbol": config.quantdinger_symbol,
        "checked_at": now,
    }
    try:
        data = _get(base + "/api/health", timeout=0.3)
        out["ok"] = True
        out["health_path"] = "/api/health"
        out["health"] = data if isinstance(data, dict) else {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"/api/health:{type(exc).__name__}"
        _PROBE_FAIL_UNTIL = time.time() + 20.0
    return out


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def local_btc_research() -> dict[str, Any]:
    """Deterministic BTC pack for 15m Kalshi — always available."""
    snap = fast_snapshot()
    spot = snap.get("spot") or {}
    win = snap.get("window") or {}
    kalshi = snap.get("kalshi") or {}
    active = kalshi.get("active") or win
    micro = {}
    try:
        from .micro import fetch_microstructure

        micro = fetch_microstructure("BTC") or {}
    except Exception:  # noqa: BLE001
        micro = {}

    price = spot.get("price") or micro.get("price")
    open_px = active.get("open_of_window") or win.get("open_of_window")
    yes_mid = active.get("yes_mid") if active.get("yes_mid") is not None else win.get("yes_mid")
    yes_ask = active.get("yes_ask") if active.get("yes_ask") is not None else win.get("yes_ask")
    yes_bid = active.get("yes_bid") if active.get("yes_bid") is not None else win.get("yes_bid")
    no_ask = active.get("no_ask") if active.get("no_ask") is not None else win.get("no_ask")
    secs = active.get("seconds_left") if active.get("seconds_left") is not None else win.get("seconds_left")

    delta = None
    delta_pct = None
    if price is not None and open_px:
        delta = price - open_px
        delta_pct = (delta / open_px) * 100.0

    fair = snap.get("fair_yes")
    edge = None
    if fair is not None and yes_mid is not None:
        edge = float(fair) - float(yes_mid)

    rsi = micro.get("rsi_14")
    funding = float(micro.get("funding_rate_pct") or 0.0)
    polarity = float((snap.get("kalshi") or {}).get("polarity") or 0.0)

    # Model-style scores (0-1) for HUD + judge
    trend = 0.5
    if delta_pct is not None:
        trend = _clamp(0.5 + delta_pct / 0.25, 0.0, 1.0)
    elif rsi is not None:
        trend = _clamp(float(rsi) / 100.0, 0.0, 1.0)

    book_lean = 0.5
    if yes_mid is not None:
        book_lean = _clamp(float(yes_mid), 0.0, 1.0)

    fair_lean = fair if fair is not None else 0.5
    signal = 0.5
    if fair is not None:
        # fair leads book — weight it higher
        signal = _clamp(0.65 * float(fair) + 0.35 * book_lean, 0.0, 1.0)

    disagreement = abs(float(fair_lean) - book_lean) if fair is not None else 0.0
    # Action lean for 15m YES/NO
    if signal >= 0.58:
        lean = "YES"
        conf = _clamp((signal - 0.5) * 2.0, 0.0, 0.95)
    elif signal <= 0.42:
        lean = "NO"
        conf = _clamp((0.5 - signal) * 2.0, 0.0, 0.95)
    else:
        lean = "SKIP"
        conf = _clamp(1.0 - abs(signal - 0.5) * 4.0, 0.0, 0.5)

    return {
        "ok": True,
        "source": "quantdinger-local-btc",
        "symbol": "BTC-USD / Kalshi KXBTC15M",
        "exchange_hint": config.quantdinger_symbol,
        "price": price,
        "open_of_window": open_px,
        "delta_from_open": round(delta, 2) if delta is not None else None,
        "delta_pct": round(delta_pct, 4) if delta_pct is not None else None,
        "seconds_left": secs,
        "kalshi": {
            "ticker": active.get("ticker") or win.get("ticker"),
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "yes_mid": yes_mid,
        },
        "spot_source": spot.get("source"),
        "spot_latency_ms": spot.get("latency_ms"),
        "book_latency_ms": (snap.get("latency") or {}).get("book_ms"),
        "micro": {
            "rsi_14": rsi,
            "funding_rate_pct": micro.get("funding_rate_pct"),
            "change_24h_pct": micro.get("change_24h_pct"),
            "open_interest_usd": micro.get("open_interest_usd"),
        },
        "models": {
            "fair_yes": round(float(fair_lean), 3) if fair is not None else None,
            "book_yes": round(book_lean, 3) if yes_mid is not None else None,
            "trend_score": round(trend, 3),
            "edge_vs_book": round(edge, 4) if edge is not None else None,
            "disagreement": round(disagreement, 3),
            "composite_signal": round(signal, 3),
        },
        "decision": {
            "lean": lean,
            "confidence": round(conf, 3),
            "reason": (
                f"qd-btc fair={fair_lean:.2f} book={book_lean:.2f} "
                f"Δ={delta_pct if delta_pct is not None else 0:+.3f}% "
                f"edge={edge if edge is not None else 0:+.3f}"
            ),
        },
        "last_print": (snap.get("latency") or {}).get("last_print"),
        "ts": time.time(),
    }


def btc_research_pack(force: bool = False) -> dict[str, Any]:
    """Cached QD probe + local BTC pack — 3s cache, never block the desk."""
    global _CACHE
    now = time.time()
    if (
        not force
        and _CACHE.get("pack")
        and now - float(_CACHE.get("ts") or 0) < 3.0
    ):
        return dict(_CACHE["pack"])
    try:
        qd = probe_quantdinger()
    except Exception:  # noqa: BLE001
        qd = {"ok": False, "configured": True, "error": "probe-crash"}
    try:
        local = local_btc_research()
    except Exception as exc:  # noqa: BLE001
        local = {"ok": False, "error": str(exc)[:120]}
    pack = {
        "quantdinger": qd,
        "btc": local,
        "used_in_decision": True,
        "integration": {
            "name": "QuantDinger",
            "symbol": config.quantdinger_symbol,
            "base_url": config.quantdinger_base_url,
            "mode": "api" if qd.get("ok") else "local-fallback",
            "note": "15m Kalshi BTC decisions include this pack; risk gate still vetoes.",
        },
        "ts": now,
    }
    _CACHE = {"ts": now, "pack": pack}
    return pack


def judgment_overlay(pack: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map research pack → fields the judge/spin can merge."""
    pack = pack or btc_research_pack()
    btc = pack.get("btc") or {}
    dec = btc.get("decision") or {}
    models = btc.get("models") or {}
    conf = float(dec.get("confidence") or 0.0)
    lean = str(dec.get("lean") or "SKIP").upper()
    # Only pass a directional lean when edge/disagreement is meaningful
    edge = float(models.get("edge_vs_book") or 0.0)
    disagreement = float(models.get("disagreement") or 0.0)
    use_lean = lean in {"YES", "NO"} and (abs(edge) >= 0.04 or disagreement >= 0.08) and conf >= 0.55
    return {
        "src": "quantdinger-btc",
        "lean": lean if use_lean else "SKIP",
        "raw_lean": lean,
        "conf": conf if use_lean else min(conf, 0.49),
        "edge_vs_book": edge,
        "composite_signal": models.get("composite_signal"),
        "fair_yes": models.get("fair_yes"),
        "book_yes": models.get("book_yes"),
        "reason": dec.get("reason") or "",
        "qd_online": bool((pack.get("quantdinger") or {}).get("ok")),
        "detail": btc,
    }
