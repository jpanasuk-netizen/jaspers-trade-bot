"""Shared desk state for the :3000 trading-blocks HUD."""
from __future__ import annotations

import threading
import time
from typing import Any

from . import spin
from .config import config
from .judge import judge
from .market import snapshot
from .sentiment import get_sentiment

_LOCK = threading.Lock()
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


def current() -> dict[str, Any]:
    quant: dict[str, Any] = {}
    qd: dict[str, Any] = {}
    charts: dict[str, Any] = {}
    try:
        from .quant import desk_quant_snapshot

        quant = desk_quant_snapshot()
    except Exception as exc:  # noqa: BLE001
        quant = {"error": str(exc)[:120]}
    try:
        from .quantdinger import btc_research_pack, probe_quantdinger

        qd = btc_research_pack()
    except Exception as exc:  # noqa: BLE001
        qd = {"error": str(exc)[:120]}
    try:
        from .chart_data import chart_series

        charts = chart_series()
    except Exception as exc:  # noqa: BLE001
        charts = {"error": str(exc)[:80]}
    btcc: dict[str, Any] = {}
    try:
        from .btcc_knowledge import btcc_signal_board

        btcc = btcc_signal_board()
    except Exception as exc:  # noqa: BLE001
        btcc = {"error": str(exc)[:120]}
    with _LOCK:
        return {
            "started_at": _STATE["started_at"],
            "connection": _STATE["connection"],
            "latest": _STATE["latest"],
            "events": list(_STATE["events"][-80:]),
            "last_spin": _STATE["last_spin"],
            "last_judgment": _STATE["last_judgment"],
            "snapshot": _STATE["snapshot"],
            "scoreboard": _STATE["scoreboard"],
            "error": _STATE["error"],
            "market_fresh": _STATE.get("market_fresh"),
            "quant": quant,
            "quantdinger": qd,
            "btcc": btcc,
            "charts": charts,
            "meta": {
                "model": "jev-15m-kalshi",
                "architecture": getattr(config, "architecture", "jev-regime-adaptive"),
                "jevModel": getattr(config, "typesafe_model", "jev-1.13.0"),
                "jevEnabled": getattr(config, "jev_enabled", True),
                "layer2Enabled": getattr(config, "layer2_enabled", False),
                "market": config.series_ticker,
                "dryRun": not spin.live_armed(),
                "liveTrading": spin.live_armed(),
                "stakeUsd": config.stake_usd,
                "host": config.host,
                "port": config.port,
                "typesafeConfigured": bool(config.typesafe_api_key),
                "twitterConfigured": bool(
                    getattr(config, "twitter_api_key", "")
                    or getattr(config, "twitter_bearer", "")
                    or getattr(config, "twitter_access_token", "")
                ),
                "martingale": getattr(config, "martingale_enabled", False),
                "martingaleTarget": getattr(config, "martingale_target", 6.0),
                "retryStake": getattr(config, "retry_stake_usd", 2.0),
                "baseStake": getattr(config, "base_stake_usd", 0.05),
            },
        }


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
        return current()
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _STATE["connection"] = "reconnecting"
            _STATE["error"] = str(exc)[:300]
        return current()
