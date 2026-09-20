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
    if conf < config.jev_conf_floor or features.get("data_age_ok") is False:
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
        "toxic_flow": round(float(features.get("vpin_proxy") or 0.0), 3),
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
            # Attach Layer-1 derived toxic flow if JEV didn't provide numeric toxic
            if j.get("toxic_flow") is None:
                j["toxic_flow"] = features.get("vpin_proxy")
        else:
            j = deterministic_judge(mkt, sent, features)
            j["typesafe_error"] = jev.get("error") or "jev unavailable"
            j["jev_latency_ms"] = jev.get("latency_ms")
    else:
        j = deterministic_judge(mkt, sent, features)
        if not config.typesafe_api_key:
            j["typesafe_error"] = "TYPESAFE_API_KEY missing; Layer-1 only"

    # ---- QuantDinger BTC research (15m decision input) ----
    qd_pack = None
    qd_overlay = None
    if getattr(config, "quantdinger_enabled", True) and getattr(config, "quantdinger_in_decisions", True):
        try:
            from .quantdinger import btc_research_pack, judgment_overlay

            qd_pack = btc_research_pack()
            qd_overlay = judgment_overlay(qd_pack)
            # Feed JEV/deterministic state with BTC model scores
            if isinstance(j, dict):
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
                # Nudge: if desk is undecided but QD-BTC has a real edge, adopt lean
                route_now = str(j.get("route") or "CONTINUE").upper()
                side_now = str(j.get("side") or "SKIP").upper()
                min_conf = float(getattr(config, "quantdinger_min_conf", 0.55))
                min_edge = float(getattr(config, "quantdinger_min_edge", 0.04))
                qd_lean = str(qd_overlay.get("lean") or "SKIP").upper()
                qd_conf = float(qd_overlay.get("conf") or 0)
                qd_edge = abs(float(qd_overlay.get("edge_vs_book") or 0))
                if (
                    qd_lean in {"YES", "NO"}
                    and qd_conf >= min_conf
                    and qd_edge >= min_edge
                    and (side_now not in {"YES", "NO"} or route_now == "SKIP")
                ):
                    j["side"] = qd_lean
                    j["action"] = qd_lean
                    j["route"] = "CONTINUE"
                    j["conf"] = max(float(j.get("conf") or 0), qd_conf)
                    probs = dict(j.get("probabilities") or {})
                    if qd_lean == "YES":
                        probs["yes"] = round(max(float(probs.get("yes") or 0), qd_conf), 3)
                    else:
                        probs["no"] = round(max(float(probs.get("no") or 0), qd_conf), 3)
                    j["probabilities"] = probs
                    j["trade_action"] = (
                        "BUY" if qd_lean == "YES" else "SELL"
                    ) if str(j.get("trade_action") or "") in {"", "HOLD", "SKIP"} else j.get("trade_action")
                    j["reason"] = (j.get("reason") or "") + f" | QD-BTC {qd_lean} {qd_conf:.2f}"
                    j["decision_sources"] = list(dict.fromkeys(
                        list(j.get("decision_sources") or []) + ["quantdinger-btc"]
                    ))
        except Exception as exc:  # noqa: BLE001
            if isinstance(j, dict):
                j["quantdinger_error"] = str(exc)[:160]

    if isinstance(j, dict) and "decision_sources" not in j:
        srcs = [str(j.get("judge_src") or "unknown")]
        if j.get("quantdinger"):
            srcs.append("quantdinger-btc")
        j["decision_sources"] = srcs

    # ---- Grokbot BTCC knowledge (fib/golden pocket + Hurst + hygiene) ----
    btcc_board = None
    btcc_ovl = None
    try:
        from .btcc_knowledge import btcc_signal_board, judgment_overlay_from_btcc, note_trade

        btcc_board = btcc_signal_board()
        btcc_ovl = judgment_overlay_from_btcc(btcc_board)
        if isinstance(j, dict):
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
            }
            # Hygiene hard veto — OVERRIDE off unless BTCC_HYGIENE_ENFORCE
            enforce_hyg = bool(getattr(config, "btcc_hygiene_enforce", False))
            if (
                enforce_hyg
                and btcc_ovl.get("hygiene_veto")
                and j.get("side") in {"YES", "NO"}
            ):
                j["side"] = "SKIP"
                j["action"] = "SKIP"
                j["trade_action"] = "HOLD"
                j["route"] = "SKIP"
                j["reason"] = (j.get("reason") or "") + " | BTCC_HYGIENE:" + ",".join(
                    btcc_ovl.get("hygiene_flags") or []
                )[:120]
            # Adopt BTCC lean when confident enough (recover mode — take the shot)
            elif (
                str(btcc_ovl.get("lean") or "SKIP").upper() in {"YES", "NO"}
                and float(btcc_ovl.get("conf") or 0) >= 0.55
            ):
                current_side = str(j.get("side") or "SKIP").upper()
                qd = j.get("quantdinger") or {}
                # if desk undecided OR BTCC setup is stronger, use BTCC
                if current_side not in {"YES", "NO"} or str(btcc_ovl.get("setup") or "") in {
                    "SETUP",
                    "HIGH CONFLUENCE",
                }:
                    j["side"] = btcc_ovl["lean"]
                    j["action"] = btcc_ovl["lean"]
                    if str(j.get("route") or "") == "SKIP":
                        j["route"] = "CONTINUE"
                    j["conf"] = max(float(j.get("conf") or 0), float(btcc_ovl.get("conf") or 0))
                    probs = dict(j.get("probabilities") or {})
                    if btcc_ovl["lean"] == "YES":
                        probs["yes"] = round(max(float(probs.get("yes") or 0), float(btcc_ovl.get("conf") or 0)), 3)
                    else:
                        probs["no"] = round(max(float(probs.get("no") or 0), float(btcc_ovl.get("conf") or 0)), 3)
                    j["probabilities"] = probs
                    if str(j.get("trade_action") or "") in {"", "HOLD", "SKIP"}:
                        j["trade_action"] = "BUY" if btcc_ovl["lean"] == "YES" else "SELL"
                    j["reason"] = (j.get("reason") or "") + f" | BTCC {btcc_ovl.get('setup')} {btcc_ovl['lean']}"
            j["decision_sources"] = list(
                dict.fromkeys(list(j.get("decision_sources") or []) + ["grokbot-btcc"])
            )
            j["btcc"]["override"] = not enforce_hyg
            j["btcc"]["risk_mode"] = btcc_board.get("risk_mode") if btcc_board else None
    except Exception as exc:  # noqa: BLE001
        if isinstance(j, dict):
            j["btcc_error"] = str(exc)[:160]

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
