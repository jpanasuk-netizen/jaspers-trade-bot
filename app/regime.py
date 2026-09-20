"""Layer 1 — deterministic regime + feature engine (us-ms, no model)."""
from __future__ import annotations

import math
import time
from typing import Any

_REGIME_CACHE: dict[str, Any] = {"ts": 0.0, "key": None, "features": None}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _rolling_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _rolling_std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _rolling_mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _bocpd_alarm(deltas: list[float], window: int = 4) -> float:
    """Simple changepoint proxy: |mean recent - mean prior| / pooled std."""
    if len(deltas) < window * 2:
        return 0.0
    recent = deltas[-window:]
    prior = deltas[-window * 2 : -window]
    m_r, m_p = _rolling_mean(recent), _rolling_mean(prior)
    s = max(_rolling_std(prior + recent), 1e-6)
    return _clamp(abs(m_r - m_p) / s, 0.0, 3.0)


def _ofi_proxy(delta_from_open: float | None, delta_pct: float | None, yes_mid: float | None) -> float:
    """Order-flow imbalance stand-in from window momentum + book lean."""
    mom = 0.0
    if delta_pct is not None:
        mom = _clamp(delta_pct / 0.25, -1.0, 1.0)
    elif delta_from_open is not None:
        mom = _clamp(delta_from_open / 80.0, -1.0, 1.0)
    book = _clamp((yes_mid - 0.5) * 2.0, -1.0, 1.0) if yes_mid is not None else 0.0
    return _clamp(0.65 * mom + 0.35 * book, -1.0, 1.0)


def _vpin_proxy(polarity: float, funding: float, squeeze_risk: float) -> float:
    """Toxicity stand-in in [0,1]. Higher = more informed/toxic flow."""
    panic = _clamp(-polarity, 0.0, 1.0)
    crowded = _clamp(abs(funding) * 40.0, 0.0, 1.0)
    return _clamp(0.45 * panic + 0.25 * crowded + 0.30 * (squeeze_risk / 100.0), 0.0, 1.0)


def _hmm_regime(delta_pct: float | None, rsi: float | None, funding: float, polarity: float) -> dict[str, Any]:
    """Lightweight regime posteriors (trend / mean_revert / high_vol / crisis)."""
    p = {"trending": 0.25, "mean_reverting": 0.25, "high_vol": 0.25, "crisis": 0.25}
    abs_dp = abs(delta_pct or 0.0)
    if abs_dp > 0.12:
        p["trending"] += 0.35
        p["mean_reverting"] -= 0.08
    elif abs_dp < 0.03:
        p["mean_reverting"] += 0.30
        p["trending"] -= 0.08
    if rsi is not None:
        if rsi >= 70 or rsi <= 30:
            p["high_vol"] += 0.25
            p["mean_reverting"] += 0.10
        if rsi >= 78 or rsi <= 22:
            p["crisis"] += 0.15
    if abs(funding) > 0.04:
        p["high_vol"] += 0.20
        p["crisis"] += 0.10
    if polarity <= -0.35 or polarity >= 0.55:
        p["crisis"] += 0.20
        p["high_vol"] += 0.10
    # softmax-ish normalize
    for k in p:
        p[k] = max(0.02, p[k])
    s = sum(p.values())
    for k in p:
        p[k] = round(p[k] / s, 3)
    top = max(p, key=lambda k: p[k])
    return {"regime": top, "regime_probs": p, "regime_conf": p[top]}


def build_layer1_state(
    mkt: dict[str, Any],
    sent: dict[str, Any],
    recent_deltas: list[float] | None = None,
) -> dict[str, Any]:
    """Deterministic structured state for JEV + risk. Dense, numeric, pre-decision only."""
    global _REGIME_CACHE
    spot = mkt.get("spot") or {}
    win = mkt.get("window") or {}
    active = (mkt.get("kalshi") or {}).get("active") or {}
    stats = sent.get("stats") or {}
    micro = sent.get("micro") or {}

    price = spot.get("price") or micro.get("price")
    open_px = win.get("open_of_window") or active.get("open_of_window")
    delta = win.get("delta_from_open")
    delta_pct = win.get("delta_pct")
    if delta is None and price is not None and open_px:
        delta = price - open_px
        delta_pct = (delta / open_px) * 100.0 if open_px else None

    yes_mid = win.get("yes_mid")
    if yes_mid is None:
        yes_mid = active.get("yes_mid")
    yes_ask = active.get("yes_ask")
    yes_bid = active.get("yes_bid")
    no_ask = active.get("no_ask")
    no_bid = active.get("no_bid")
    try:
        yes_ask = float(yes_ask) if yes_ask is not None else None
        yes_bid = float(yes_bid) if yes_bid is not None else None
        no_ask = float(no_ask) if no_ask is not None else None
        no_bid = float(no_bid) if no_bid is not None else None
    except (TypeError, ValueError):
        yes_ask = yes_bid = no_ask = no_bid = None

    spread = None
    if yes_ask is not None and yes_bid is not None:
        spread = round(yes_ask - yes_bid, 4)

    rsi = micro.get("rsi_14")
    funding = float(micro.get("funding_rate_pct") or 0.0)
    polarity = float(stats.get("polarity_score") or 0.0)
    squeeze = float(micro.get("squeeze_risk_pct") or 0.0)
    if not squeeze:
        squeeze = _clamp(35.0 + (-polarity * 40.0) + (max(0.0, -funding) * 400.0), 0.0, 95.0)

    deltas = list(recent_deltas or [])
    if delta is not None:
        deltas = (deltas + [float(delta)])[-24:]

    bocpd = _bocpd_alarm(deltas)
    ofi = _ofi_proxy(delta, delta_pct, yes_mid)
    vpin = _vpin_proxy(polarity, funding, squeeze)
    hmm = _hmm_regime(delta_pct, float(rsi) if rsi is not None else None, funding, polarity)

    # Volatility proxy: window move + RSI extremes + funding crowding
    vol_proxy = _clamp(
        abs(delta_pct or 0.0) / 0.20 + abs((rsi or 50) - 50.0) / 40.0 + abs(funding) * 10.0,
        0.0,
        3.0,
    )
    liquidity_stressed = _clamp(
        (0.4 if spread is not None and spread >= 0.08 else 0.0)
        + (0.3 if (yes_mid is not None and (yes_mid <= 0.08 or yes_mid >= 0.92)) else 0.0)
        + (0.3 if vol_proxy > 1.4 else 0.0),
        0.0,
        1.0,
    )

    seconds_left = win.get("seconds_left")
    # 1s poll desk: last seconds of the window are still a live market, not "stale".
    # Only treat as dead once the window is closed.
    data_age_ok = seconds_left is None or float(seconds_left) > 0.0

    features = {
        "ts": time.time(),
        "venue": "Kalshi KXBTC15M",
        "asset": "BTC",
        "price": price,
        "open_of_window": open_px,
        "delta_from_open": round(delta, 2) if delta is not None else None,
        "delta_pct": round(delta_pct, 4) if delta_pct is not None else None,
        "yes_mid": yes_mid,
        "yes_ask": yes_ask,
        "yes_bid": yes_bid,
        "no_ask": no_ask,
        "no_bid": no_bid,
        "book_spread": spread,
        "rsi_14": rsi,
        "funding_rate_pct": funding,
        "change_24h_pct": micro.get("change_24h_pct"),
        "open_interest_usd": micro.get("open_interest_usd"),
        "polarity_score": polarity,
        "social_label": stats.get("sentiment_label") or "Neutral / Mixed",
        "social_sample": stats.get("sample_size") or 0,
        "squeeze_risk_pct": round(squeeze, 1),
        "bocpd_alarm": round(bocpd, 3),
        "ofi_proxy": round(ofi, 3),
        "vpin_proxy": round(vpin, 3),
        "vol_proxy": round(vol_proxy, 3),
        "liquidity_stressed_proxy": round(liquidity_stressed, 3),
        "data_age_ok": data_age_ok,
        "seconds_left": seconds_left,
        "ticker": win.get("ticker"),
        "window_id": win.get("window_id"),
        **hmm,
    }
    _REGIME_CACHE = {"ts": features["ts"], "key": features.get("window_id"), "features": features}
    return features


def jev_triggers(features: dict[str, Any]) -> list[str]:
    """Events that justify firing the JEV battery (or escalating)."""
    t: list[str] = []
    if float(features.get("bocpd_alarm") or 0) >= 0.85:
        t.append("bocpd_alarm")
    if features.get("regime") in {"high_vol", "crisis"}:
        t.append("regime_transition")
    if abs(float(features.get("polarity_score") or 0)) >= 0.35:
        t.append("news_or_social_event")
    if float(features.get("vol_proxy") or 0) >= 1.5:
        t.append("high_volatility")
    if features.get("data_age_ok") is False:
        t.append("stale_state")
    return t
