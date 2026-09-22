"""YES/NO judgment — JEV regime-adaptive architecture.

Layer 1   deterministic stats (regime.py)     us–ms
Layer 1.5 JEV typed battery (jev_layer.py)    70–500ms
Layer 2   multi-agent escalation (optional)
Risk      hard vetoes (risk_gate.py) — always wins
Execute   spin/execution code — never the model
"""
from __future__ import annotations

import time
from typing import Any

from .config import config
from .market import snapshot
from .micro import fetch_microstructure
from .regime import build_layer1_state, jev_triggers
from .risk_gate import evaluate_risk_gate
from .sentiment import get_sentiment

_JUDGE_CACHE: dict[str, Any] = {"ts": 0.0, "window_id": None, "judgment": None}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def deterministic_judge(mkt: dict[str, Any], sent: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    """Layer-1 fallback when JEV is unavailable (still triage + risk gated)."""
    stats = sent.get("stats") or {}
    micro = sent.get("micro") or {}
    polarity = float(stats.get("polarity_score") or features.get("polarity_score") or 0.0)
    delta = features.get("delta_from_open")
    delta_pct = features.get("delta_pct")
    yes_mid = features.get("yes_mid")
    rsi = features.get("rsi_14")
    funding = float(features.get("funding_rate_pct") or 0.0)

    if delta_pct is None and delta is not None:
        delta_pct = _clamp(delta / 50.0, -2.0, 2.0)
    mom = _clamp((delta_pct or 0.0) / 25.0, -0.25, 0.25)
    sen = _clamp(-0.12 * polarity, -0.12, 0.12)
    book = _clamp((yes_mid - 0.5) * 0.35, -0.18, 0.18) if yes_mid is not None else 0.0
    rsi_bias = 0.0
    if rsi is not None:
        rsi_bias = _clamp((50.0 - float(rsi)) / 200.0, -0.15, 0.15)
    funding_bias = _clamp(-funding * 8.0, -0.10, 0.10)
    ofi_bias = _clamp(float(features.get("ofi_proxy") or 0.0) * 0.08, -0.08, 0.08)

    p_yes = _clamp(0.5 + mom + sen + book + rsi_bias + funding_bias + ofi_bias, 0.05, 0.95)
    p_no = 1.0 - p_yes
    conf = abs(p_yes - 0.5) * 2.0
    data_quality = 0.55
    if features.get("price") is not None:
        data_quality += 0.15
    if features.get("open_of_window"):
        data_quality += 0.15
    if yes_mid is not None:
        data_quality += 0.10
    if not sent.get("is_mock"):
        data_quality += 0.05
    conf = _clamp(conf * min(1.0, data_quality), 0.0, 0.98)

    # Toxic / quality proxies for the risk gate
    toxic = float(features.get("vpin_proxy") or 0.0)
    quality = _clamp(1.0 - toxic - float(features.get("liquidity_stressed_proxy") or 0.0) * 0.4, 0.0, 1.0)

    route = "CONTINUE"
    if conf < config.jev_conf_floor:
        route = "SKIP"
    elif float(features.get("bocpd_alarm") or 0) >= 0.85 or features.get("regime") == "crisis":
        route = "ESCALATE" if config.layer2_enabled else "SKIP"

    if route == "SKIP":
        action = side = "SKIP"
        trade_action = "HOLD"
    elif p_yes >= p_no:
        action = side = "YES"
        trade_action = "BUY" if conf < 0.75 else "STRONG_BUY"
    else:
        action = side = "NO"
        trade_action = "SELL" if conf < 0.75 else "STRONG_SELL"

    reasons = [
        f"det+regime={features.get('regime')}",
        f"ofi={features.get('ofi_proxy')}",
        f"bocpd={features.get('bocpd_alarm')}",
        f"route={route}",
    ]
    if delta is not None:
        reasons.insert(0, f"Δopen {delta:+.1f}")
    reasons.append(f"X-pol {polarity:+.2f}")

    return {
        "ok": True,
        "judge_src": "layer1-deterministic",
        "model": "jev-15m-layer1",
        "is_mock": bool(sent.get("is_mock")),
        "action": action,
        "side": side,
        "route": route,
        "conf": round(conf, 3),
        "clear_edge": round(max(p_yes, p_no) if side in {"YES", "NO"} else conf, 3),
        "probabilities": {
            "yes": round(p_yes, 3),
            "no": round(p_no, 3),
            "skip": 0.0 if side in {"YES", "NO"} else round(1.0 - conf, 3),
            "buy": round(p_yes, 3),
            "sell": round(p_no, 3),
            "hold": round(1.0 - conf, 3),
        },
        "trade_action": trade_action,
        "sentiment_label": stats.get("sentiment_label") or features.get("social_label") or "Neutral / Mixed",
        "polarity_score": polarity,
        "squeeze_risk_pct": float(features.get("squeeze_risk_pct") or 0.0),
        "catalyst_impact_score": 0.0,
        "signal_quality": round(quality, 3),
        "toxic_flow": round(toxic, 3),
        "decision_consistency": 0.55,
        "should_escalate": 0.4 if route == "ESCALATE" else 0.15,
        "reason": " · ".join(reasons),
        "spot": features.get("price"),
        "open_of_window": features.get("open_of_window"),
        "delta_from_open": delta,
        "delta_pct": delta_pct,
        "yes_mid": yes_mid,
        "architecture": {"layer": "1-deterministic", "route": route},
    }


def _apply_jev_to_shell(jev: dict[str, Any], features: dict[str, Any], sent: dict[str, Any]) -> dict[str, Any]:
    """Normalize JEV battery output onto the desk judgment shape."""
    stats = sent.get("stats") or {}
    probs = jev.get("probabilities") or {}
    return {
        "ok": True,
        "judge_src": "jev",
        "model": jev.get("model"),
        "model_pinned": jev.get("model_pinned"),
        "is_mock": False,
        "action": jev.get("action"),
        "side": jev.get("side"),
        "route": jev.get("route"),
        "conf": jev.get("conf"),
        "clear_edge": jev.get("clear_edge"),
        "probabilities": probs,
        "trade_action": jev.get("trade_action"),
        "sentiment_label": jev.get("sentiment_label") or features.get("social_label"),
        "polarity_score": jev.get("polarity_score"),
        "squeeze_risk_pct": jev.get("squeeze_risk_pct"),
        "catalyst_impact_score": 0.0,
        "signal_quality": jev.get("signal_quality"),
        "toxic_flow": round(float(jev.get("toxic_flow") if jev.get("toxic_flow") is not None else features.get("vpin_proxy") or 0.0), 3),
        "decision_consistency": jev.get("decision_consistency"),
        "should_escalate": jev.get("should_escalate"),
        "regime_confirm": jev.get("regime_confirm"),
        "news_relevant": jev.get("news_relevant"),
        "latency_ms": jev.get("latency_ms"),
        "reason": jev.get("reason"),
        "spot": features.get("price"),
        "open_of_window": features.get("open_of_window"),
        "delta_from_open": features.get("delta_from_open"),
        "delta_pct": features.get("delta_pct"),
        "yes_mid": features.get("yes_mid"),
        "window": {},
        "social_stats": stats,
        "market": {
            "price": features.get("price"),
            "rsi_14": features.get("rsi_14"),
            "funding_rate_pct": features.get("funding_rate_pct"),
        },
        "architecture": jev.get("architecture"),
        "raw_answers": jev.get("raw_answers"),
    }


def _collect_desk_inputs() -> dict[str, Any]:
    """Every other desk gets a say. None of them set the side."""
    compact: dict[str, Any] = {
        "note": "Inputs only. Jev decides YES, NO, or SKIP.",
    }
    out: dict[str, Any] = {"compact": compact, "qd_overlay": None, "btcc_board": None, "btcc_ovl": None, "ai": None, "errors": {}}
    if getattr(config, "quantdinger_enabled", True) and getattr(config, "quantdinger_in_decisions", True):
        try:
            from .quantdinger import btc_research_pack, judgment_overlay

            overlay = judgment_overlay(btc_research_pack())
            out["qd_overlay"] = overlay
            compact["quantdinger"] = {
                "lean": overlay.get("lean"),
                "conf": overlay.get("conf"),
                "fair_yes": overlay.get("fair_yes"),
                "edge_vs_book": overlay.get("edge_vs_book"),
            }
        except Exception as exc:  # noqa: BLE001
            out["errors"]["quantdinger"] = str(exc)[:160]
    try:
        from .btcc_knowledge import btcc_signal_board, judgment_overlay_from_btcc

        board = btcc_signal_board()
        overlay = judgment_overlay_from_btcc(board)
        out["btcc_board"] = board
        out["btcc_ovl"] = overlay
        compact["btcc"] = {
            "lean": overlay.get("lean"),
            "conf": overlay.get("conf"),
            "setup": overlay.get("setup"),
            "hurst": overlay.get("hurst"),
        }
    except Exception as exc:  # noqa: BLE001
        out["errors"]["btcc"] = str(exc)[:160]
    try:
        from .ai_trader import btc_crowd

        crowd = btc_crowd()
        out["ai"] = crowd
        compact["ai_trader"] = {
            "lean": crowd.get("lean"),
            "buys": crowd.get("buys"),
            "sells": crowd.get("sells"),
            "agents": crowd.get("agents"),
        }
    except Exception as exc:  # noqa: BLE001
        out["errors"]["ai_trader"] = str(exc)[:160]
    return out


def judge(force: bool = False) -> dict[str, Any]:
    """Full regime-adaptive path: L1 → JEV → (L2) → risk gate → judgment."""
    global _JUDGE_CACHE
    now = time.time()
    t0 = time.time()
    mkt = snapshot()
    win = mkt.get("window") or {}
    window_id = win.get("window_id") or win.get("ticker") or "none"

    if (
        not force
        and _JUDGE_CACHE.get("judgment") is not None
        and _JUDGE_CACHE.get("window_id") == window_id
        and now - float(_JUDGE_CACHE.get("ts") or 0) < config.judge_ttl_sec
    ):
        j = dict(_JUDGE_CACHE["judgment"])
        j["cached"] = True
        j["window"] = win
        j["spot"] = (mkt.get("spot") or {}).get("price")
        return j

    sent = get_sentiment("BTC", force=force)
    if not (sent.get("micro") or {}):
        sent = dict(sent)
        sent["micro"] = fetch_microstructure("BTC")

    # ---- Layer 1: deterministic state / regime ----
    features = build_layer1_state(mkt, sent)
    triggers = jev_triggers(features)

    # ---- Other desks, before Jev, so they are inputs and not a second vote ----
    try:
        from .finance_db import btc_listings

        features["finance_db"] = btc_listings()
    except Exception:  # noqa: BLE001
        pass
    desks = _collect_desk_inputs()
    features["desks"] = desks["compact"]

    # ---- Layer 1.5: JEV typed battery (one batched call) ----
    j: dict[str, Any] | None = None
    jev_meta: dict[str, Any] = {}
    if config.jev_enabled and config.typesafe_api_key:
        from .jev_layer import call_jev_battery

        sample = (sent.get("stats") or {}).get("stratified_sample") or []
        jev = call_jev_battery(features, sample)
        jev_meta = jev
        if jev.get("ok"):
            j = _apply_jev_to_shell(jev, features, sent)
            if j.get("toxic_flow") is None:
                j["toxic_flow"] = features.get("vpin_proxy")
        else:
            j = deterministic_judge(mkt, sent, features)
            j["typesafe_error"] = jev.get("error") or "jev unavailable"
            j["jev_latency_ms"] = jev.get("latency_ms")
            if jev.get("hold") or jev.get("judge_src") == "jev_stale":
                # Only a real miss past JEV_TIMEOUT_SEC (2.5s). A 1–2s answer
                # is on time for this loop. Other desks do not take the shot.
                j["side"] = "SKIP"
                j["action"] = "SKIP"
                j["route"] = "SKIP"
                j["trade_action"] = "HOLD"
                j["reason"] = (j.get("reason") or "") + " | JEV_STALE_HOLD"
    else:
        j = deterministic_judge(mkt, sent, features)
        if not config.typesafe_api_key:
            j["typesafe_error"] = "TYPESAFE_API_KEY missing; Layer-1 only"

    # Desks are attached for the HUD. They already went into the Jev snapshot.
    # They do not change side, route, or confidence.
    qd_overlay = desks.get("qd_overlay") or {}
    btcc_ovl = desks.get("btcc_ovl") or {}
    btcc_board = desks.get("btcc_board") or {}
    if isinstance(j, dict):
        if qd_overlay:
            j["quantdinger"] = {
                "lean": qd_overlay.get("lean"),
                "raw_lean": qd_overlay.get("raw_lean"),
                "conf": qd_overlay.get("conf"),
                "edge_vs_book": qd_overlay.get("edge_vs_book"),
                "fair_yes": qd_overlay.get("fair_yes"),
                "book_yes": qd_overlay.get("book_yes"),
                "composite_signal": qd_overlay.get("composite_signal"),
                "qd_online": qd_overlay.get("qd_online"),
                "reason": qd_overlay.get("reason"),
                "symbol": getattr(config, "quantdinger_symbol", "BTC/USDT"),
            }
        elif desks.get("errors", {}).get("quantdinger"):
            j["quantdinger_error"] = desks["errors"]["quantdinger"]
        if btcc_ovl:
            j["btcc"] = {
                "lean": btcc_ovl.get("lean"),
                "raw_lean": btcc_ovl.get("raw_lean"),
                "setup": btcc_ovl.get("setup"),
                "conf": btcc_ovl.get("conf"),
                "hurst": btcc_ovl.get("hurst"),
                "hygiene_veto": btcc_ovl.get("hygiene_veto"),
                "hygiene_flags": btcc_ovl.get("hygiene_flags"),
                "in_golden_pocket": btcc_ovl.get("in_golden_pocket"),
                "edge_vs_book": btcc_ovl.get("edge_vs_book"),
                "signals": btcc_ovl.get("signals"),
                "reason": btcc_ovl.get("reason"),
                "override": False,
                "risk_mode": btcc_board.get("risk_mode") if isinstance(btcc_board, dict) else None,
            }
        elif desks.get("errors", {}).get("btcc"):
            j["btcc_error"] = desks["errors"]["btcc"]
        j["ai_trader"] = desks.get("ai") or {"lean": "SKIP", "error": desks.get("errors", {}).get("ai_trader")}
        srcs = [str(j.get("judge_src") or "unknown")]
        if j.get("quantdinger"):
            srcs.append("quantdinger-btc")
        if j.get("btcc"):
            srcs.append("grokbot-btcc")
        if (j.get("ai_trader") or {}).get("lean") not in {None, "SKIP"}:
            srcs.append("ai-trader")
        j["decision_sources"] = list(dict.fromkeys(srcs))

    # ---- Layer 2 escalate stub (optional NVIDIA/kimi or other reasoning) ----
    # JEV never owns execution; escalated cases without L2 are blocked by risk gate.
    route = str(j.get("route") or "CONTINUE").upper()
    if route == "ESCALATE" and config.layer2_enabled:
        j["layer2"] = {
            "requested": True,
            "configured": bool(config.layer2_base_url or config.nvidia_api_key),
            "note": "Layer-2 available; still subject to hard risk gate",
        }
    elif route == "ESCALATE":
        j["layer2"] = {"requested": True, "configured": False, "note": "no Layer-2; risk will block"}

    # Enrich desk fields
    j["microstructure"] = sent.get("micro") or j.get("microstructure") or {}
    j["social_source"] = sent.get("source") or j.get("social_source")
    j["x_sample"] = (sent.get("stats") or {}).get("sample_size")
    j["x_polarity"] = (sent.get("stats") or {}).get("polarity_score")
    j["window"] = win
    j["kalshi_active"] = (mkt.get("kalshi") or {}).get("active")
    j["market_snapshot"] = mkt.get("spot")
    j["judged_at"] = now
    j["layer1"] = {
        "regime": features.get("regime"),
        "regime_probs": features.get("regime_probs"),
        "bocpd_alarm": features.get("bocpd_alarm"),
        "ofi_proxy": features.get("ofi_proxy"),
        "vpin_proxy": features.get("vpin_proxy"),
        "vol_proxy": features.get("vol_proxy"),
        "liquidity_stressed_proxy": features.get("liquidity_stressed_proxy"),
        "triggers": triggers,
        "data_age_ok": features.get("data_age_ok"),
    }
    j["features"] = features

    # ---- Risk gate (absolute veto; code owns capital) ----
    decision_latency_ms = (time.time() - t0) * 1000.0
    risk = evaluate_risk_gate(
        j,
        features,
        day_pnl=None,
        stake_usd=config.stake_usd,
        decision_latency_ms=decision_latency_ms,
    )
    j["risk"] = risk
    j["decision_latency_ms"] = round(decision_latency_ms, 1)
    if risk.get("blocked") and j.get("side") in {"YES", "NO"}:
        j["risk_blocked"] = True
        j["side"] = "SKIP"
        j["action"] = "SKIP"
        j["trade_action"] = "HOLD"
        j["reason"] = (j.get("reason") or "") + " | RISK_BLOCK:" + ",".join(risk.get("reasons") or [])[:160]

    j["architecture_pipeline"] = [
        "L1-deterministic",
        "L1.5-jev" if (j.get("judge_src") == "jev") else "L1-fallback",
        "L2-escalate" if route == "ESCALATE" and config.layer2_enabled else "L2-skipped",
        "risk-gate",
        "execution-owned-by-code",
    ]

    _JUDGE_CACHE = {"ts": now, "window_id": window_id, "judgment": j}
    return j
