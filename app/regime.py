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


# Causal HMM. States match the router: quiet, informed flow, thin liquidity.
# Live code keeps only the forward filter α_t = P(S_t | y_1..y_t).
# A smoothed posterior γ_t = P(S_t | y_1..y_T) uses the future and is not computed.
_STATES = ("quiet", "informed_flow", "thin_liquidity")
_CEILING = {"quiet": 3, "informed_flow": 2, "thin_liquidity": 1}
_PIN_SECONDS = 60.0
# Rows are the state we were in. Columns are the state we step into.
_TRANS = (
    (0.90, 0.06, 0.04),
    (0.10, 0.82, 0.08),
    (0.12, 0.08, 0.80),
)
# Emissions on (abs return, abs ofi, kyle λ, spread), each scaled to about [0, 1].
_MU = {
    "quiet": (0.15, 0.18, 0.20, 0.12),
    "informed_flow": (0.72, 0.68, 0.78, 0.28),
    "thin_liquidity": (0.28, 0.22, 0.40, 0.86),
}
_VAR = 0.07
_FILTER = {"alpha": [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0], "n": 0}


def reset_filter() -> None:
    """Start the forward filter from a uniform prior. Tests call this."""
    _FILTER["alpha"] = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
    _FILTER["n"] = 0


def _kyle_lambda(abs_return: float, abs_ofi: float) -> float:
    """Price impact per unit of flow. High when price moves on little flow."""
    return _clamp(abs_return / max(abs_ofi, 0.12), 0.0, 1.0)


def _emission(obs: tuple[float, float, float, float]) -> list[float]:
    likes: list[float] = []
    for name in _STATES:
        mu = _MU[name]
        dist = 0.0
        for i, value in enumerate(obs):
            gap = value - mu[i]
            dist += (gap * gap) / _VAR
        likes.append(math.exp(-0.5 * dist))
    return likes


def _forward_filter(obs: tuple[float, float, float, float]) -> list[float]:
    """One causal update. The previous α is the only memory. No backward pass."""
    prev = _FILTER["alpha"]
    predicted = [0.0, 0.0, 0.0]
    for i in range(3):
        for j in range(3):
            predicted[j] += prev[i] * _TRANS[i][j]
    liked = _emission(obs)
    raw = [predicted[j] * liked[j] for j in range(3)]
    total = sum(raw) or 1e-12
    alpha = [value / total for value in raw]
    _FILTER["alpha"] = alpha
    _FILTER["n"] = int(_FILTER["n"]) + 1
    return alpha


def filtered_regime(
    delta_pct: float | None,
    ofi: float,
    spread: float | None,
    seconds_left: float | None,
) -> dict[str, Any]:
    """Filtered regime label plus the pin overlay. Not a smoothed posterior."""
    abs_return = _clamp(abs(delta_pct or 0.0) / 0.25, 0.0, 1.0)
    abs_ofi = _clamp(abs(ofi), 0.0, 1.0)
    kyle = _kyle_lambda(abs_return, abs_ofi)
    if spread is None:
        spread_z = 0.20
    else:
        spread_z = _clamp(float(spread) / 0.10, 0.0, 1.0)
    alpha = _forward_filter((abs_return, abs_ofi, kyle, spread_z))
    probs = {name: round(alpha[i], 4) for i, name in enumerate(_STATES)}
    top = max(_STATES, key=lambda name: probs[name])
    pin = False
    try:
        pin = seconds_left is not None and float(seconds_left) <= _PIN_SECONDS
    except (TypeError, ValueError):
        pin = False
    return {
        "regime": top,
        "regime_probs": probs,
        "regime_conf": probs[top],
        "prob_kind": "filtered",
        "kyle_lambda": round(kyle, 4),
        "pin_overlay": pin,
        "filter_steps": int(_FILTER["n"]),
    }


def jev_size_tier(conf: float, side: str) -> int:
    """Jev proposes a size tier. 0 means no order. Code may only lower this."""
    if str(side or "").upper() not in {"YES", "NO"}:
        return 0
    score = float(conf or 0.0)
    if score >= 0.75:
        return 3
    if score >= 0.60:
        return 2
    return 1


def regime_router(
    features: dict[str, Any],
    *,
    side: str,
    conf: float,
    order_budget: float,
) -> dict[str, Any]:
    """final tier = min(Jev tier, regime ceiling, pin ceiling)."""
    regime = str(features.get("regime") or "thin_liquidity")
    regime_ceiling = int(_CEILING.get(regime, 1))
    pin = bool(features.get("pin_overlay"))
    ceiling = 1 if pin else regime_ceiling
    if pin:
        ceiling = min(regime_ceiling, 1)
    proposed = jev_size_tier(conf, side)
    final = min(proposed, ceiling) if proposed else 0
    budget = round(float(order_budget) * (final / 3.0), 4) if final else 0.0
    return {
        "prob_kind": "filtered",
        "regime": regime,
        "regime_conf": features.get("regime_conf"),
        "kyle_lambda": features.get("kyle_lambda"),
        "jev_tier": proposed,
        "regime_ceiling": regime_ceiling,
        "pin_overlay": pin,
        "ceiling": ceiling,
        "final_tier": final,
        "budget_usd": budget,
        "rule": "final = min(jev_tier, regime_ceiling, pin_ceiling)",
    }


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
    seconds_left = win.get("seconds_left")
    hmm = filtered_regime(delta_pct, ofi, spread, seconds_left)

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
    if features.get("regime") == "thin_liquidity":
        t.append("thin_liquidity")
    if features.get("pin_overlay"):
        t.append("pin_overlay")
    if abs(float(features.get("polarity_score") or 0)) >= 0.35:
        t.append("news_or_social_event")
    if float(features.get("vol_proxy") or 0) >= 1.5:
        t.append("high_volatility")
    if features.get("data_age_ok") is False:
        t.append("stale_state")
    return t
