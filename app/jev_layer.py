"""Layer 1.5 — JEV (TypeSafe System One) fast typed judgment battery.

Blueprint: RohOnChain https://x.com/RohOnChain/status/2101311813908652069
  Code computes state. Jev interprets with a parallel battery. Code applies
  policy. Hard risk vetoes never go to the model. Direct api.typesafe.ai.
  If the call is not back before the next loop, HOLD.

Jev does not replace Layer 1 (deterministic stats), Layer 2, or execution.
"""
from __future__ import annotations

import time
from typing import Any

from .config import config

SENTIMENT_LEVELS = [
    "Extreme Panic / Capitulation",
    "Cautious / Bearish",
    "Neutral / Mixed",
    "Optimistic / Bullish",
    "Euphoric / Greedy",
]


def _norm_prob(v: Any) -> float:
    try:
        x = float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return x / 100.0 if x > 1.0 else x


def _norm_conf(v: Any) -> float:
    try:
        x = float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return x / 100.0 if x > 1.0 else x


def _choice_payload(ans: Any) -> dict[str, Any]:
    choice = getattr(ans, "choice", None)
    if choice is None and isinstance(ans, dict):
        choice = ans.get("choice") or ans.get("value")
    conf = _norm_conf(getattr(ans, "confidence", ans.get("confidence") if isinstance(ans, dict) else 0.0))
    raw = getattr(ans, "probabilities", None)
    if raw is None and isinstance(ans, dict):
        raw = ans.get("probabilities") or {}
    probs = {str(k): _norm_prob(v) for k, v in (raw or {}).items()}
    return {"choice": str(choice or "").strip(), "confidence": conf, "probabilities": probs}


def _noul_payload(ans: Any, default: float = 0.5) -> float:
    val = getattr(ans, "noul", None)
    if val is None and isinstance(ans, dict):
        val = ans.get("noul", ans.get("value"))
    if val is None:
        return default
    return _norm_prob(val)


def _score_payload(ans: Any, levels: list[str]) -> tuple[float, str]:
    sc = getattr(ans, "score", None)
    if sc is None and isinstance(ans, dict):
        sc = ans.get("score", ans.get("value"))
    try:
        sc_f = float(sc if sc is not None else 2.0)
    except (TypeError, ValueError):
        sc_f = 2.0
    # SDK may return 0-based index or already 0..n-1 float
    idx = int(round(sc_f))
    if idx < 0:
        idx = 0
    if idx >= len(levels):
        idx = len(levels) - 1
    return sc_f, levels[idx]


def build_jev_state(features: dict[str, Any], social_sample: list[Any] | None = None) -> dict[str, Any]:
    """Compact numeric state (<~400 tokens). Pre-decision facts only."""
    return {
        "venue": features.get("venue"),
        "asset": features.get("asset"),
        "window": {
            "ticker": features.get("ticker"),
            "window_id": features.get("window_id"),
            "open_of_window": features.get("open_of_window"),
            "seconds_left": features.get("seconds_left"),
        },
        "price": features.get("price"),
        "delta_from_open": features.get("delta_from_open"),
        "delta_pct": features.get("delta_pct"),
        "kalshi": {
            "yes_mid": features.get("yes_mid"),
            "yes_ask": features.get("yes_ask"),
            "yes_bid": features.get("yes_bid"),
            "no_ask": features.get("no_ask"),
            "no_bid": features.get("no_bid"),
            "book_spread": features.get("book_spread"),
        },
        "microstructure": {
            "rsi_14": features.get("rsi_14"),
            "funding_rate_pct": features.get("funding_rate_pct"),
            "change_24h_pct": features.get("change_24h_pct"),
            "open_interest_usd": features.get("open_interest_usd"),
        },
        "layer1_stats": {
            "regime": features.get("regime"),
            "regime_probs": features.get("regime_probs"),
            "bocpd_alarm": features.get("bocpd_alarm"),
            "ofi_proxy": features.get("ofi_proxy"),
            "vpin_proxy": features.get("vpin_proxy"),
            "vol_proxy": features.get("vol_proxy"),
            "liquidity_stressed_proxy": features.get("liquidity_stressed_proxy"),
        },
        "social_stats": {
            "polarity_score": features.get("polarity_score"),
            "sentiment_label": features.get("social_label"),
            "sample_size": features.get("social_sample"),
        },
        "representative_tweets": (social_sample or [])[:8],
        "policy": {
            "conf_floor": config.conf_floor,
            "note": "JEV triage only; code applies risk and execution.",
        },
    }


def build_battery_questions() -> dict[str, Any] | None:
    """Parallel typed questions — Choice / Noul / Score in one call."""
    try:
        from typesafe_sdk import Choice, Noul, Score  # type: ignore
    except Exception:  # noqa: BLE001
        return None

    return {
        # Regime confirm (architecture: is this a real regime shift?)
        "regime_confirm": Choice(
            instructions=(
                "Using `layer1_stats` and price/momentum fields, what regime best "
                "describes this BTC 15m Kalshi window state right now?"
            ),
            criteria={
                "trending": "Directional continuation is the dominant structure.",
                "mean_reverting": "Chop / fade / range is the dominant structure.",
                "chaotic": "No stable structure; book and flow disagree.",
                "high_vol": "Volatility expansion without a clean directional edge.",
                "crisis": "Disorderly move, panic/euphoria, or stress regime.",
            },
        ),
        "toxic_flow": Noul(
            instructions=(
                "Is current flow informed/toxic (adverse selection) rather than noise, "
                "given `layer1_stats.vpin_proxy`, `ofi_proxy`, and `kalshi` book?"
            ),
            criteria={
                "true": "Informed/toxic flow — do not take the other side blindly.",
                "false": "Noise or uninformed flow.",
            },
        ),
        # News / social relevance
        "news_relevant": Noul(
            instructions=(
                "Is `social_stats` (and `representative_tweets` if present) relevant "
                "to this window's settlement direction, not just generic crypto noise?"
            ),
            criteria={
                "true": "Social/news content materially informs YES/NO for this window.",
                "false": "Noise, unrelated chatter, or stale sentiment.",
            },
        ),
        # Decision consistency with Layer 1
        "decision_consistent": Noul(
            instructions=(
                "Do `layer1_stats` (regime, ofi_proxy, bocpd, delta) and `kalshi` book "
                "lean together without major contradiction for a tradable 15m view?"
            ),
            criteria={
                "true": "Signals are coherent enough for a typed side judgment.",
                "false": "Signals conflict; prefer SKIP / escalate.",
            },
        ),
        # Escalation trigger
        "should_escalate": Noul(
            instructions=(
                "Should this state be escalated to a slower multi-agent reasoning layer "
                "instead of acting on a fast judgment alone?"
            ),
            criteria={
                "true": (
                    "Escalate: regime crisis, BOCPD shock, toxic flow, stale data, "
                    "or high-stakes ambiguity."
                ),
                "false": "Fast typed judgment is sufficient for triage.",
            },
        ),
        # Settlement side — the primary typed judgment
        "side": Choice(
            instructions=(
                "For this Kalshi BTC 15m window, will settlement be ABOVE "
                "`window.open_of_window` (YES), BELOW it (NO), or no clear edge (SKIP)? "
                "Use categorical judgment only — do not invent numeric targets."
            ),
            criteria={
                "YES": "Settlement likely above open_of_window.",
                "NO": "Settlement likely below open_of_window.",
                "SKIP": "No clear edge or conflicting state.",
            },
        ),
        # Signal quality / adverse selection
        "signal_quality": Score(
            instructions=(
                "Rate the quality/consistency of the decision environment for taking "
                "a 15m YES/NO position (not PnL expectation)."
            ),
            criteria=[
                "Toxic / adverse — do not trade",
                "Weak / noisy setup",
                "Acceptable setup",
                "Clean high-quality setup",
            ],
        ),
        # Social mood (Jev-X compatible)
        "sentiment_spectrum": Score(
            instructions="Rate the prevailing social mood in `social_stats`.",
            criteria=SENTIMENT_LEVELS,
        ),
        # Squeeze risk
        "is_short_squeeze_risk": Noul(
            instructions=(
                "Does funding + panic/social state suggest short-squeeze risk into YES "
                "before this 15m window closes?"
            ),
            criteria={
                "true": "Squeeze into YES is a live risk.",
                "false": "No material squeeze setup.",
            },
        ),
        # Trade action (Jev-X style, still categorical)
        "trade_action": Choice(
            instructions=(
                "Categorical action for this state mapped to 15m Kalshi direction. "
                "Triage only — execution is owned by code."
            ),
            criteria={
                "STRONG_BUY": "High-conviction YES window.",
                "BUY": "Favorable YES.",
                "HOLD": "No clear 15m edge.",
                "TAKE_PROFIT": "Favor NO / fade the move.",
                "SELL": "Favorable NO.",
                "STRONG_SELL": "High-conviction NO window.",
            },
        ),
    }


def call_jev_battery(features: dict[str, Any], social_sample: list[Any] | None = None) -> dict[str, Any]:
    """One System One call → typed battery answers + routing decision."""
    t0 = time.time()
    if not config.typesafe_api_key:
        return {
            "ok": False,
            "judge_src": "jev_unavailable",
            "error": "TYPESAFE_API_KEY not configured",
            "latency_ms": 0.0,
        }
    questions = build_battery_questions()
    if questions is None:
        return {
            "ok": False,
            "judge_src": "jev_unavailable",
            "error": "typesafe_sdk not installed",
            "latency_ms": 0.0,
        }

    state = build_jev_state(features, social_sample)
    model = config.typesafe_model  # pin; do not use moving alias for thresholds
    timeout = max(0.2, float(getattr(config, "jev_timeout_sec", 0.8)))
    base_url = getattr(config, "typesafe_base_url", "https://api.typesafe.ai") or "https://api.typesafe.ai"

    try:
        from typesafe_sdk import TypeSafeClient  # type: ignore

        import os

        os.environ.setdefault("TYPESAFE_API_KEY", config.typesafe_api_key)
        os.environ.setdefault("TYPESAFE_BASE_URL", base_url)
        kw: dict[str, Any] = {"api_key": config.typesafe_api_key, "timeout": timeout, "base_url": base_url}
        try:
            from typesafe_sdk import RetryPolicy  # type: ignore

            kw["retry"] = RetryPolicy(max_retries=0)
        except Exception:  # noqa: BLE001
            pass
        try:
            client = TypeSafeClient(**kw)
        except TypeError:
            client = TypeSafeClient(api_key=config.typesafe_api_key)
        with client as c:
            try:
                response = c.system_one(state=state, questions=questions, model=model, timeout=timeout)
            except TypeError:
                response = c.system_one(state=state, questions=questions)
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        stale = "timeout" in name.lower() or "timeout" in str(exc).lower()
        return {
            "ok": False,
            "judge_src": "jev_stale" if stale else "jev_error",
            "error": str(exc)[:240],
            "hold": True if stale else False,
            "latency_ms": (time.time() - t0) * 1000.0,
        }

    answers = getattr(response, "answers", None) or {}
    used_model = getattr(response, "model", None) or model
    latency_ms = (time.time() - t0) * 1000.0

    side_ans = _choice_payload(answers.get("side"))
    regime_ans = _choice_payload(answers.get("regime_confirm"))
    action_ans = _choice_payload(answers.get("trade_action"))
    news_p = _noul_payload(answers.get("news_relevant"), 0.3)
    consist_p = _noul_payload(answers.get("decision_consistent"), 0.5)
    escalate_p = _noul_payload(answers.get("should_escalate"), 0.2)
    squeeze_p = _noul_payload(answers.get("is_short_squeeze_risk"), 0.15)
    toxic_p = _noul_payload(answers.get("toxic_flow"), float(features.get("vpin_proxy") or 0.0))
    quality_f, quality_label = _score_payload(
        answers.get("signal_quality"),
        ["Toxic / adverse — do not trade", "Weak / noisy setup", "Acceptable setup", "Clean high-quality setup"],
    )
    sent_f, sent_label = _score_payload(answers.get("sentiment_spectrum"), SENTIMENT_LEVELS)

    side_raw = (side_ans.get("choice") or "SKIP").upper()
    if side_raw not in {"YES", "NO", "SKIP"}:
        side_raw = "SKIP"
    conf = side_ans.get("confidence") or 0.0
    probs = side_ans.get("probabilities") or {}
    p_yes = probs.get("YES", probs.get("yes", 0.0)) or 0.0
    p_no = probs.get("NO", probs.get("no", 0.0)) or 0.0
    if p_yes <= 0 and p_no <= 0:
        if side_raw == "YES":
            p_yes, p_no = max(conf, 0.5), 1 - max(conf, 0.5)
        elif side_raw == "NO":
            p_yes, p_no = 1 - max(conf, 0.5), max(conf, 0.5)
        else:
            p_yes = p_no = 0.5
    if side_raw == "YES":
        conf = max(conf, p_yes)
    elif side_raw == "NO":
        conf = max(conf, p_no)

    trade_action = (action_ans.get("choice") or "").upper() or (
        "BUY" if side_raw == "YES" else "SELL" if side_raw == "NO" else "HOLD"
    )

    # Confidence-gated routing (code owns policy)
    # Architecture: CONTINUE | ESCALATE | SKIP
    conf_ok = conf >= config.jev_conf_floor
    consist_ok = consist_p >= config.jev_consistency_min
    quality_ok = quality_f >= config.signal_quality_min
    toxic_ok = toxic_p <= config.toxic_flow_max
    # Late window is not an escalate trigger on a 1s poller.
    escalate = escalate_p >= config.jev_escalate_prob
    if not conf_ok or not consist_ok or side_raw == "SKIP" or not toxic_ok:
        route = "SKIP"
    elif escalate:
        route = "ESCALATE"
    elif not quality_ok:
        route = "SKIP"
    else:
        route = "CONTINUE"

    # Map lean for HUD / spin
    side = side_raw
    if route == "CONTINUE" and side == "SKIP" and config.trade_on_lean:
        if p_yes > p_no and p_yes >= config.jev_conf_floor:
            side = "YES"
        elif p_no > p_yes and p_no >= config.jev_conf_floor:
            side = "NO"

    action = side if side in {"YES", "NO"} else "SKIP"
    edge = max(p_yes, p_no) if side in {"YES", "NO"} else conf

    if route == "SKIP":
        action = "SKIP"
        if side not in {"YES", "NO"}:
            side = "SKIP"
        trade_action = "HOLD"
    elif route == "ESCALATE":
        # Do not auto-trade escalated cases without Layer-2; risk gate will block.
        trade_action = trade_action if trade_action else "HOLD"

    quality_norm = _clamp01(quality_f / 3.0) if quality_f <= 3.0 else _clamp01(quality_f)

    return {
        "ok": True,
        "judge_src": "jev",
        "model": used_model,
        "model_pinned": config.typesafe_model,
        "latency_ms": round(latency_ms, 1),
        "route": route,
        "side": side,
        "action": action,
        "trade_action": trade_action,
        "conf": round(conf, 3),
        "clear_edge": round(edge, 3),
        "probabilities": {
            "yes": round(p_yes, 3),
            "no": round(p_no, 3),
            "skip": round(1.0 - max(p_yes, p_no), 3) if side_raw == "SKIP" else 0.0,
            "buy": round(p_yes, 3),
            "sell": round(p_no, 3),
            "hold": round(1.0 - max(p_yes, p_no), 3),
        },
        "side_raw": side_raw,
        "regime_confirm": regime_ans.get("choice") or "",
        "regime_conf": regime_ans.get("confidence") or 0.0,
        "news_relevant": round(news_p, 3),
        "decision_consistency": round(consist_p, 3),
        "should_escalate": round(escalate_p, 3),
        "signal_quality": round(quality_norm, 3),
        "signal_quality_raw": quality_f,
        "signal_quality_label": quality_label,
        "sentiment_label": sent_label,
        "sentiment_score": sent_f,
        "squeeze_risk_pct": round(squeeze_p * 100.0, 1),
        "toxic_flow": round(toxic_p, 3),
        "blueprint": "RohOnChain/2101311813908652069",
        "polarity_score": float(features.get("polarity_score") or 0.0),
        "reason": (
            f"jev {used_model} route={route} side={side_raw} "
            f"conf={conf:.2f} q={quality_f:.1f} consist={consist_p:.2f} "
            f"esc={escalate_p:.2f} regime={regime_ans.get('choice')}"
        ),
        "architecture": {
            "layer": "1.5-jev",
            "route": route,
            "latency_ms": round(latency_ms, 1),
            "questions": list(questions.keys()),
            "api": "https://api.typesafe.ai/v1/systemone",
            "blueprint": "RohOnChain/2101311813908652069",
        },
        "raw_answers": {
            k: {
                "choice": getattr(v, "choice", None),
                "noul": getattr(v, "noul", None),
                "score": getattr(v, "score", None),
                "confidence": getattr(v, "confidence", None),
            }
            for k, v in answers.items()
        },
    }


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
