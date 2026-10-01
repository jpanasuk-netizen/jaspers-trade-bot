"""Hard risk gate — absolute veto. Jev never owns these checks."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .config import config

_KILL_PATHS = [
    Path.home() / ".beat15m" / "KILL_SWITCH",
    Path.home() / ".beat15m" / "KILL",
    config.data_dir / "KILL_SWITCH",
]


def _kill_switch_on() -> str | None:
    env = (os.environ.get("KILL_SWITCH") or "").strip().lower()
    if env in {"1", "true", "on", "yes", "kill"}:
        return "kill_switch_env"
    for p in _KILL_PATHS:
        try:
            if p.is_file() and p.read_text(encoding="utf-8").strip():
                return f"kill_switch_file:{p}"
        except Exception:  # noqa: BLE001
            continue
    return None


def evaluate_risk_gate(
    judgment: dict[str, Any],
    features: dict[str, Any],
    *,
    day_pnl: float | None = None,
    stake_usd: float | None = None,
    decision_latency_ms: float | None = None,
) -> dict[str, Any]:
    """Return {passed, blocked, checks[]}. ANY failed check => no trade."""
    checks: list[dict[str, Any]] = []
    conf = float(judgment.get("conf") or 0.0)
    edge = float(judgment.get("clear_edge") or 0.0)
    signal_quality = float(judgment.get("signal_quality") or 0.0)
    toxic = float(judgment.get("toxic_flow") or 0.0)
    side = str(judgment.get("side") or "SKIP").upper()
    route = str(judgment.get("route") or "CONTINUE").upper()

    def add(name: str, ok: bool, rule: str, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "rule": rule, "detail": detail})

    # Kill switch / manual stop
    kill = _kill_switch_on()
    add("kill_switch", kill is None, "file/env kill switch off", kill or "clear")

    # Day loss limit
    pnl = day_pnl if day_pnl is not None else 0.0
    add(
        "loss_limit",
        pnl > -config.day_loss_stop_usd(),
        f"day loss < {config.day_loss_stop_usd():.2f}",
        f"day_pnl={pnl:.2f}",
    )

    # Jev / policy confidence floor
    if side in {"YES", "NO"}:
        add(
            "jev_confidence",
            conf >= config.conf_floor,
            f"conf >= {config.conf_floor}",
            f"conf={conf:.3f}",
        )
        if config.edge_floor > 0:
            add(
                "clear_edge",
                edge >= config.edge_floor,
                f"edge >= {config.edge_floor}",
                f"edge={edge:.3f}",
            )

    # Adverse selection / signal quality
    add(
        "signal_quality",
        signal_quality >= config.signal_quality_min,
        f"signal_quality >= {config.signal_quality_min}",
        f"signal_quality={signal_quality:.2f}",
    )

    # Toxic flow — informed/toxic book, do not provide/take blindly
    add(
        "toxic_flow",
        toxic <= config.toxic_flow_max,
        f"toxic_flow <= {config.toxic_flow_max}",
        f"toxic_flow={toxic:.3f}",
    )

    # Volatility / spread block
    vol = float(features.get("vol_proxy") or 0.0)
    add(
        "volatility",
        vol <= config.max_vol_proxy,
        f"vol_proxy <= {config.max_vol_proxy}",
        f"vol_proxy={vol:.3f}",
    )
    spread = features.get("book_spread")
    if spread is not None:
        add(
            "spread",
            float(spread) <= config.max_book_spread,
            f"book_spread <= {config.max_book_spread}",
            f"spread={spread}",
        )

    # Book integrity — a junk 0.001/0.999 print is not market certainty.
    def _px_ok(v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        if x > 1.5:
            x = x / 100.0
        if x < 0.01 or x > 0.99:
            return None
        return x

    yb = _px_ok(features.get("yes_bid"))
    ya = _px_ok(features.get("yes_ask"))
    book_ok = True
    book_detail = "clean"
    if yb is not None and ya is not None and yb > ya:
        book_ok = False
        book_detail = f"crossed yes_bid={yb:.3f} > yes_ask={ya:.3f}"
    elif yb is None and ya is None:
        book_ok = False
        book_detail = "no usable yes bid/ask"
    elif (yb is not None and yb >= 0.99) or (ya is not None and ya <= 0.01):
        book_ok = False
        book_detail = f"degenerate print yes_bid={yb} yes_ask={ya}"
    add(
        "book_integrity",
        book_ok,
        "book is a real two-sided print (no 0.001/0.999 junk, not crossed)",
        book_detail,
    )

    # Liquidity stress
    liq = float(features.get("liquidity_stressed_proxy") or 0.0)
    add(
        "liquidity",
        liq <= config.max_liquidity_stress,
        f"liquidity_stress <= {config.max_liquidity_stress}",
        f"liq={liq:.3f}",
    )

    # JEV path foresight — block buying into a predicted second move against us.
    fc = judgment.get("jev_forecast") or {}
    p_up = float(fc.get("p_next_up") or 0.0)
    p_dn = float(fc.get("p_next_down") or 0.0)
    bounce_p = float(fc.get("will_bounce_p") or 0.5)
    nxt = str(fc.get("next_big_move") or "QUIET").upper()
    path = str(fc.get("settle_path") or "EVEN").upper()
    foresight_ok = True
    foresight_detail = f"next={nxt} bounce={bounce_p:.2f} path={path}"
    foresight_rule = "path forecast not fighting the side"
    if side == "YES" and nxt == "DOWN" and max(p_dn, 0.0) >= 0.55:
        foresight_ok = False
        foresight_rule = "skip YES when Jev forecasts next impulse DOWN (p_next_down>=0.55)"
    elif side == "NO" and nxt == "UP" and max(p_up, 0.0) >= 0.55:
        foresight_ok = False
        foresight_rule = "skip NO when Jev forecasts next impulse UP (p_next_up>=0.55)"
    elif side in {"YES", "NO"} and path == "GIVE_BACK" and bounce_p >= 0.65:
        foresight_ok = False
        foresight_rule = "skip when Jev says the Δ will GIVE_BACK (bounce>=0.65)"
    add("jev_foresight", foresight_ok, foresight_rule, foresight_detail)

    # Window still open = live. A 1s poller will often arrive with 1–7s left;
    # that is not stale. If Jev already said YES/NO, fire while the market exists.
    secs = features.get("seconds_left")
    try:
        secs_f = float(secs) if secs is not None else None
    except (TypeError, ValueError):
        secs_f = None
    jev_fire = side in {"YES", "NO"} and str(judgment.get("judge_src") or "").startswith("jev")
    if secs_f is not None and secs_f <= 0.0:
        window_open = False
        detail = f"window_closed seconds_left={secs}"
        rule = "window still open (seconds_left > 0)"
    else:
        window_open = secs_f is None or secs_f > 0.0
        detail = f"seconds_left={secs}"
        rule = "window still open (1s poll; Jev fire allowed into the close)"
    add(
        "data_freshness",
        window_open if jev_fire else (bool(features.get("data_age_ok", True)) or window_open),
        rule,
        detail,
    )

    # Decision latency: HFT deadline does not apply. If Jev already answered
    # FIRE, place it — 1s poll + ~1s TypeSafe RTT routinely exceeds 1500ms.
    if decision_latency_ms is not None:
        lat_ok = decision_latency_ms <= config.max_decision_latency_ms or jev_fire
        add(
            "decision_latency",
            lat_ok,
            f"latency <= {config.max_decision_latency_ms}ms or Jev FIRE",
            f"{decision_latency_ms:.0f}ms jev_fire={jev_fire}",
        )

    # Escalation without Layer-2 reasoning → hold (architecture: escalate then risk)
    if route == "ESCALATE" and not config.layer2_enabled:
        add(
            "layer2_available",
            False,
            "escalate requires Layer-2 reasoning or hold",
            "no Layer-2 configured; route=ESCALATE",
        )
    else:
        add("layer2_available", True, "route not blocked", route)

    # Exposure / stake cap
    stake = float(stake_usd if stake_usd is not None else config.stake_usd)
    add(
        "exposure",
        stake <= config.max_stake_usd + 1e-9,
        f"stake <= {config.max_stake_usd}",
        f"stake={stake:.4f}",
    )

    # Day halt mirror
    add(
        "day_halt",
        pnl > -config.day_loss_stop_usd(),
        "not day-halted",
        f"pnl={pnl:.2f}",
    )

    # Grokbot BTCC — OVERRIDE: hygiene OFF unless BTCC_HYGIENE_ENFORCE=1
    # Hard keep: no auto 500x (not a Kalshi path) + survive via day-stop / stake cap
    enforce = bool(getattr(config, "btcc_hygiene_enforce", False))
    btcc = judgment.get("btcc") or {}
    hygiene_veto = bool(btcc.get("hygiene_veto")) and enforce
    hflags = btcc.get("hygiene_flags") or []
    add(
        "btcc_hygiene",
        not hygiene_veto,
        "hygiene override off" if not enforce else "Grokbot BTCC hygiene clear",
        ("override:" + ",".join(hflags) if (hflags and not enforce) else (",".join(hflags) if hflags else "clear")),
    )
    # No auto 500x — Kalshi stake is capped; leverage bots are not this path
    add(
        "no_auto_500x",
        stake <= max(float(getattr(config, "max_stake_usd", 25.0)), 25.0),
        "no 500x auto path — Kalshi stake cap only",
        f"stake={stake:.4f}",
    )

    failed = [c for c in checks if not c["ok"]]
    passed = len(failed) == 0
    # Architecture: if ANY risk check fails, system does not trade.
    if side in {"YES", "NO"} and not passed:
        judgment = dict(judgment)
        judgment["side"] = "SKIP"
        judgment["action"] = "SKIP"
        judgment["trade_action"] = "HOLD"
        judgment["risk_blocked"] = True

    return {
        "passed": passed,
        "blocked": not passed,
        "failed": failed,
        "checks": checks,
        "verdict": "ALLOW" if passed else "BLOCK",
        "reasons": [f"{c['check']}: {c['detail']}" for c in failed],
        "evaluated_at": time.time(),
        "architecture": "layer-risk-gate",
    }
