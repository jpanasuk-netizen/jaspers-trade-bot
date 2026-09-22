"""Shared desk state for the :3000 trading-blocks HUD."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from . import spin
from .config import config
from .judge import judge
from .market import snapshot
from .sentiment import get_sentiment

_LOCK = threading.Lock()
_EXTRAS_AT = 0.0
_STATE: dict[str, Any] = {
    "started_at": int(time.time() * 1000),
    "connection": "connecting",
    "latest": None,
    "events": [],
    "last_spin": None,
    "last_judgment": None,
    "snapshot": None,
    "scoreboard": None,
    "error": None,
    "market_fresh": None,
}


def touch_market(snap: dict[str, Any]) -> None:
    """Publish latest market snapshot from the high-frequency loop."""
    with _LOCK:
        _STATE["snapshot"] = snap
        _STATE["market_fresh"] = {
            "ts": time.time(),
            "price": (snap.get("spot") or {}).get("price"),
            "spot_source": (snap.get("spot") or {}).get("source"),
            "ticker": (snap.get("window") or {}).get("ticker"),
            "yes_mid": (snap.get("window") or {}).get("yes_mid"),
            "yes_ask": (snap.get("window") or {}).get("yes_ask"),
            "open_of_window": (snap.get("window") or {}).get("open_of_window"),
            "fast_feed": snap.get("fast_feed"),
        }
        if _STATE.get("connection") in {None, "connecting", "reconnecting"}:
            _STATE["connection"] = "live"
    _write_hud_file()


def _hud_extras() -> dict[str, Any]:
    """Heavy panels — computed on the market/decision loops, not per HTTP GET."""
    extras: dict[str, Any] = {}
    try:
        from .quant import desk_quant_snapshot

        extras["quant"] = desk_quant_snapshot()
    except Exception as exc:  # noqa: BLE001
        extras["quant"] = {"error": str(exc)[:120]}
    try:
        from .quantdinger import btc_research_pack

        extras["quantdinger"] = btc_research_pack()
    except Exception as exc:  # noqa: BLE001
        extras["quantdinger"] = {"error": str(exc)[:120]}
    try:
        from .chart_data import chart_series

        extras["charts"] = chart_series()
    except Exception as exc:  # noqa: BLE001
        extras["charts"] = {"error": str(exc)[:80]}
    try:
        from .btcc_knowledge import btcc_signal_board

        extras["btcc"] = btcc_signal_board()
    except Exception as exc:  # noqa: BLE001
        extras["btcc"] = {"error": str(exc)[:120]}
    try:
        from .finance_db import btc_listings

        extras["finance_db"] = btc_listings()
    except Exception as exc:  # noqa: BLE001
        extras["finance_db"] = {"error": str(exc)[:120]}
    return extras


def refresh_hud_extras(force: bool = False) -> None:
    """Charts and side panels live in the trading process. Refresh them on a timer."""
    global _EXTRAS_AT
    now = time.time()
    if not force and now - _EXTRAS_AT < 5.0:
        return
    extras = _hud_extras()
    with _LOCK:
        _STATE["hud_extras"] = extras
    _EXTRAS_AT = now


def _slim_judgment(j: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(j, dict):
        return {}
    return {
        "side": j.get("side"),
        "conf": j.get("conf"),
        "route": j.get("route"),
        "judge_src": j.get("judge_src"),
        "reason": str(j.get("reason") or "")[:180],
        "spot": j.get("spot"),
        "open_of_window": j.get("open_of_window"),
        "delta_from_open": j.get("delta_from_open"),
        "fair_yes": (j.get("quantdinger") or {}).get("fair_yes") or j.get("fair_yes"),
        "layer1": _slim_layer1(j.get("layer1")),
    }


def _slim_layer1(layer1: Any) -> dict[str, Any]:
    """The six desk gauges. The full feature blob stays off the HUD payload."""
    if not isinstance(layer1, dict):
        return {}
    probs = layer1.get("regime_probs")
    if not isinstance(probs, dict):
        probs = {}
    return {
        "regime": layer1.get("regime"),
        "regime_probs": {k: probs.get(k) for k in ("trending", "mean_revert", "high_vol", "crisis") if k in probs},
        "bocpd_alarm": layer1.get("bocpd_alarm"),
        "ofi_proxy": layer1.get("ofi_proxy"),
        "vpin_proxy": layer1.get("vpin_proxy"),
        "vol_proxy": layer1.get("vol_proxy"),
        "liquidity_stressed_proxy": layer1.get("liquidity_stressed_proxy"),
        "triggers": list(layer1.get("triggers") or [])[:8],
    }


def _slim_spin(s: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s, dict):
        return {}
    try:
        from .settle import attach_outcome

        s = attach_outcome(s)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ts": s.get("ts"),
        "result": s.get("result"),
        "side": s.get("side"),
        "reason": str(s.get("reason") or s.get("spin_reason") or "")[:220],
        "stake_usd": s.get("stake_usd"),
        "entry": s.get("entry"),
        "mode": s.get("mode"),
        "ticker": s.get("ticker"),
        "won": s.get("won"),
        "outcome_side": s.get("outcome_side"),
        "filled": s.get("filled"),
    }


def current() -> dict[str, Any]:
    """Small HUD payload so the browser can actually paint."""
    with _LOCK:
        extras = dict(_STATE.get("hud_extras") or {})
        snap = _STATE.get("snapshot") or {}
        win = (snap.get("window") if isinstance(snap, dict) else {}) or {}
        spot = (snap.get("spot") if isinstance(snap, dict) else {}) or {}
        return {
            "started_at": _STATE["started_at"],
            "connection": _STATE["connection"],
            "latest": _STATE["latest"],
            "events": [
                {"ts": e.get("ts"), "spin": _slim_spin(e.get("spin") if isinstance(e, dict) else None)}
                for e in list(_STATE["events"][-12:])
                if isinstance(e, dict)
            ],
            "last_spin": _slim_spin(_STATE["last_spin"]),
            "last_judgment": _slim_judgment(_STATE["last_judgment"]),
            "snapshot": {
                "window": {
                    "ticker": win.get("ticker"),
                    "seconds_left": win.get("seconds_left"),
                    "yes_ask": win.get("yes_ask"),
                    "no_ask": win.get("no_ask"),
                    "yes_mid": win.get("yes_mid"),
                    "yes_bid": win.get("yes_bid"),
                    "open_of_window": win.get("open_of_window"),
                },
                "spot": {"price": spot.get("price"), "source": spot.get("source")},
                "fast_feed": snap.get("fast_feed") if isinstance(snap, dict) else None,
            },
            "scoreboard": _STATE["scoreboard"],
            "error": _STATE["error"],
            "market_fresh": _STATE.get("market_fresh"),
            "quant": extras.get("quant") or {},
            "quantdinger": extras.get("quantdinger") or {},
            "btcc": extras.get("btcc") or {},
            "charts": extras.get("charts") or {},
            "meta": {
                "model": "jev-15m-kalshi",
                "market": config.series_ticker,
                "dryRun": not spin.live_armed(),
                "liveTrading": spin.live_armed(),
                "host": "0.0.0.0",
                "port": config.port,
                "martingale": getattr(config, "martingale_enabled", False),
                "martingaleTarget": getattr(config, "martingale_target", 6.0),
            },
        }


def _write_hud_file() -> None:
    try:
        payload = current()
        path = config.data_dir / "hud.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, default=str, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return


def _build_block_event(j: dict[str, Any], mkt: dict[str, Any], spin_rec: dict[str, Any] | None) -> dict[str, Any]:
    win = mkt.get("window") or {}
    sb = spin._load_json(spin._paths()["scoreboard"], spin._empty_scoreboard())
    probs = j.get("probabilities") or {}
    return {
        "ts": time.time(),
        "block": int(time.time() // 15),
        "window": win,
        "spot": mkt.get("spot"),
        "kalshi": (mkt.get("kalshi") or {}).get("active"),
        "decision": {
            "action": "buy" if j.get("side") == "YES" else "sell" if j.get("side") == "NO" else "hold",
            "kalshi_side": j.get("side"),
            "trade_action": j.get("trade_action"),
            "probabilities": {
                "yes": probs.get("yes", 0),
                "no": probs.get("no", 0),
                "buy": probs.get("yes", probs.get("buy", 0)),
                "sell": probs.get("no", probs.get("sell", 0)),
                "hold": probs.get("hold", 0),
            },
            "conf": j.get("conf"),
            "clear_edge": j.get("clear_edge"),
            "reason": j.get("reason"),
            "judge_src": j.get("judge_src"),
            "side_raw": j.get("side_raw") or j.get("side"),
            "route": j.get("route"),
            "signal_quality": j.get("signal_quality"),
            "toxic_flow": j.get("toxic_flow"),
            "decision_consistency": j.get("decision_consistency"),
            "regime": (j.get("layer1") or {}).get("regime"),
        },
        "architecture": {
            "pipeline": j.get("architecture_pipeline"),
            "layer1": j.get("layer1"),
            "risk": j.get("risk"),
            "latency_ms": j.get("decision_latency_ms"),
            "model": j.get("model"),
            "route": j.get("route"),
        },
        "risk_gate": j.get("risk") or {},
        "sentiment": {
            "label": j.get("sentiment_label"),
            "polarity": j.get("polarity_score"),
            "squeeze_risk_pct": j.get("squeeze_risk_pct"),
            "catalyst": j.get("catalyst_impact_score"),
            "social_stats": j.get("social_stats") or {},
            "source": j.get("social_source") or (j.get("social_stats") or {}).get("source"),
        },
        "microstructure": j.get("microstructure") or {},
        "spin": spin_rec,
        "totals": {
            "decisions": sb.get("decisions", 0),
            "fills": sb.get("fills", 0),
            "wins": sb.get("wins", 0),
            "losses": sb.get("losses", 0),
            "pushes": sb.get("pushes", 0),
            "pnlUsd": sb.get("pnlUsd", 0.0),
        },
        "mode": "LIVE" if spin.live_armed() else "PAPER",
        "gates": {
            "stake_usd": config.stake_usd,
            "conf_floor": config.conf_floor,
            "entry_ceil": config.entry_ceil,
            "trade_on_lean": config.trade_on_lean,
        },
    }


def tick(do_spin: bool = True) -> dict[str, Any]:
    """Refresh market + judgment (+ optional spin) and publish a trading block."""
    global _STATE
    try:
        mkt = snapshot()
        j = judge(force=False)
        get_sentiment("BTC", force=False)
        spin_rec = spin.evaluate_spin(force_judge=False) if do_spin else None
        event = _build_block_event(j, mkt, spin_rec)
        sb = spin.settle_and_update_scoreboard()
        # record chart series for HUD
        try:
            from .chart_data import record_tick
            from .quantdinger import judgment_overlay

            ff = mkt.get("fast_feed") or {}
            win = mkt.get("window") or {}
            ovl = j.get("quantdinger") or judgment_overlay()
            record_tick(
                price=(mkt.get("spot") or {}).get("price"),
                yes_mid=win.get("yes_mid"),
                yes_bid=win.get("yes_bid"),
                yes_ask=win.get("yes_ask"),
                no_ask=win.get("no_ask"),
                fair_yes=ff.get("fair_yes") or ovl.get("fair_yes"),
                edge=ff.get("edge_vs_book") if ff.get("edge_vs_book") is not None else ovl.get("edge_vs_book"),
                signal=ovl.get("composite_signal"),
                side=j.get("side"),
                conf=j.get("conf"),
                open_of_window=win.get("open_of_window"),
            )
            event["quantdinger"] = j.get("quantdinger") or ovl
            event["fast_feed"] = ff
        except Exception:  # noqa: BLE001
            pass
        with _LOCK:
            _STATE["connection"] = "live"
            _STATE["snapshot"] = mkt
            _STATE["last_judgment"] = j
            _STATE["last_spin"] = spin_rec
            _STATE["scoreboard"] = sb
            _STATE["latest"] = event
            _STATE["events"] = (_STATE["events"] + [event])[-200:]
            _STATE["error"] = None
        refresh_hud_extras()
        _write_hud_file()
        return current()
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _STATE["connection"] = "reconnecting"
            _STATE["error"] = str(exc)[:300]
        return current()
