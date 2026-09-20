"""Paper/live spin engine — old JAP rules on Kalshi BTC 15m YES/NO."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import config
from .judge import judge


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths() -> dict[str, Path]:
    return {
        "ledger": config.data_dir / "spin_ledger.jsonl",
        "spun": config.data_dir / "spun_windows.json",
        "scoreboard": config.data_dir / "scoreboard.json",
        "day_pnl": config.data_dir / "day_pnl.json",
        "blocks": config.data_dir / "trading_blocks.json",
    }


def live_armed() -> bool:
    mark = config.live_mark
    if not mark.is_file():
        return False
    v = mark.read_text(encoding="utf-8").strip().lower()
    return v in {"live", "1", "go", "yes", "true"}


def _append(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def already_spun(ticker: str | None) -> bool:
    if not ticker:
        return False
    data = _load_json(_paths()["spun"], {"done": []})
    return ticker in (data.get("done") or [])


def mark_spun(ticker: str | None) -> None:
    if not ticker:
        return
    data = _load_json(_paths()["spun"], {"done": []})
    done = data.get("done") or []
    if ticker not in done:
        done.append(ticker)
    data["done"] = done[-200:]
    _save_json(_paths()["spun"], data)


def day_pnl() -> float:
    data = _load_json(_paths()["day_pnl"], {})
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("day") != day:
        return 0.0
    return float(data.get("pnl") or 0.0)


def day_halted() -> bool:
    return abs(day_pnl()) >= config.day_stop_usd


def jev_to_side(j: dict[str, Any]) -> tuple[str, float, float, str]:
    """Map judgment → YES/NO/SKIP. Open-gates: HOLD can still trade a lean."""
    action = str(j.get("action") or "hold").lower()
    side_raw = str(j.get("side") or "").upper()
    conf = float(j.get("conf") or 0.0)
    edge = float(j.get("clear_edge") or 0.0)
    reason = str(j.get("reason") or "")
    probs = j.get("probabilities") or {}
    yes_p = float(probs.get("yes") or probs.get("buy") or 0.0)
    no_p = float(probs.get("no") or probs.get("sell") or 0.0)
    trade_action = str(j.get("trade_action") or "").upper()

    if side_raw in {"YES", "NO"}:
        return side_raw, max(conf, yes_p if side_raw == "YES" else no_p), edge, reason or side_raw.lower()
    if action in {"buy", "yes"} or trade_action in {"BUY", "STRONG_BUY"}:
        return "YES", max(conf, yes_p), edge, reason or "action_yes"
    if action in {"sell", "no"} or trade_action in {"SELL", "STRONG_SELL", "TAKE_PROFIT"}:
        return "NO", max(conf, no_p), edge, reason or "action_no"

    if config.trade_on_lean:
        if yes_p > no_p and yes_p > 0:
            return "YES", max(conf, yes_p), edge, (reason or "hold") + "+lean_yes"
        if no_p > yes_p and no_p > 0:
            return "NO", max(conf, no_p), edge, (reason or "hold") + "+lean_no"

    return "SKIP", conf, edge, reason or "hold"


def _entry_for(side: str, active: dict[str, Any]) -> float | None:
    if side == "YES":
        v = active.get("yes_ask")
        return float(v) if v is not None else None
    if side == "NO":
        v = active.get("no_ask")
        return float(v) if v is not None else None
    return None


def paper_fill(side: str, entry: float, stake: float) -> dict[str, Any]:
    px = max(0.01, min(0.99, entry))
    count = max(1, int(stake / max(0.05, px)))
    while count > 1 and count * px > stake * 1.05:
        count -= 1
    cost = round(count * px, 4)
    return {
        "simulated": True,
        "book_side": "bid" if side == "YES" else "ask",
        "price": px,
        "count": count,
        "est_cost": cost,
        "fill_count": str(count),
        "filled": True,
        "fill_price": px,
        "api": "paper",
    }


def settle_and_update_scoreboard() -> dict[str, Any]:
    """Best-effort PnL update using paper ledger + current market marks."""
    paths = _paths()
    ledger_path = paths["ledger"]
    if not ledger_path.is_file():
        return _load_json(paths["scoreboard"], _empty_scoreboard())
    lines = ledger_path.read_text(encoding="utf-8").splitlines()[-500:]
    trades = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if rec.get("mode") in {"PAPER", "LIVE"} and rec.get("filled"):
            trades.append(rec)
    # placeholder scoreboard — live settle can refine later
    sb = _load_json(paths["scoreboard"], _empty_scoreboard())
    sb["decisions"] = sb.get("decisions", 0)
    sb["fills"] = len(trades)
    sb["pnlUsd"] = float(sb.get("pnlUsd") or 0.0)
    sb["wins"] = int(sb.get("wins") or 0)
    sb["losses"] = int(sb.get("losses") or 0)
    sb["pushes"] = int(sb.get("pushes") or 0)
    sb["updatedAt"] = int(time.time() * 1000)
    sb["liveArmed"] = live_armed()
    _save_json(paths["scoreboard"], sb)
    return sb


def _empty_scoreboard() -> dict[str, Any]:
    return {
        "decisions": 0,
        "fills": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "pnlUsd": 0.0,
        "stakeUsd": config.stake_usd,
        "liveArmed": live_armed(),
        "mode": "PAPER" if not live_armed() else "LIVE",
    }


def evaluate_spin(force_judge: bool = False) -> dict[str, Any]:
    """One look: judge + gates + paper/live action for the active window."""
    paths = _paths()
    j = judge(force=force_judge)
    win = j.get("window") or {}
    ticker = win.get("ticker")
    active = j.get("kalshi_active") or {}
    mode = "LIVE" if live_armed() else "PAPER"

    # Martingale plan (double-down → $6, then $2 spins)
    try:
        from . import martingale

        cash = martingale.kalshi_cash() if mode == "LIVE" else martingale.load_state().get("cash_now")
        plan = martingale.plan_stake(cash)
        if not config.martingale_enabled:
            plan = {
                "mode": "standard",
                "stake": float(config.stake_usd),
                "cash": cash,
                "target": config.martingale_target,
                "loss_streak": 0,
                "reason": "martingale disabled",
            }
        stake = float(plan.get("stake") or config.base_stake_usd)
    except Exception as exc:  # noqa: BLE001
        plan = {"mode": "error", "stake": config.stake_usd, "error": str(exc)[:120]}
        stake = float(config.stake_usd)

    rec: dict[str, Any] = {
        "ts": now_iso(),
        "mode": mode,
        "ticker": ticker,
        "window_id": win.get("window_id"),
        "seconds_left": win.get("seconds_left"),
        "spot": j.get("spot"),
        "open_of_window": j.get("open_of_window"),
        "delta_from_open": j.get("delta_from_open"),
        "stake_usd": stake,
        "martingale": plan,
        "judge": {
            "src": j.get("judge_src"),
            "action": j.get("action"),
            "side": j.get("side"),
            "trade_action": j.get("trade_action"),
            "conf": j.get("conf"),
            "clear_edge": j.get("clear_edge"),
            "probabilities": j.get("probabilities"),
            "reason": j.get("reason"),
            "sentiment_label": j.get("sentiment_label"),
            "polarity_score": j.get("polarity_score"),
            "squeeze_risk_pct": j.get("squeeze_risk_pct"),
            "route": j.get("route"),
            "signal_quality": j.get("signal_quality"),
            "toxic_flow": j.get("toxic_flow"),
            "risk": j.get("risk"),
            "layer1": j.get("layer1"),
            "architecture_pipeline": j.get("architecture_pipeline"),
        },
        "risk_gate": j.get("risk") or {},
        "architecture": {
            "pipeline": j.get("architecture_pipeline"),
            "route": j.get("route"),
            "layer1": j.get("layer1"),
            "latency_ms": j.get("decision_latency_ms"),
        },
        "gates": {
            "stake_usd": stake,
            "stake_mode": plan.get("mode"),
            "cash": plan.get("cash"),
            "target": plan.get("target"),
            "conf_floor": config.conf_floor,
            "jev_conf_floor": config.jev_conf_floor,
            "signal_quality_min": config.signal_quality_min,
            "entry_ceil": config.entry_ceil,
            "edge_floor": config.edge_floor,
            "trade_on_lean": config.trade_on_lean,
            "day_stop_usd": config.day_stop_usd,
            "max_stake_usd": config.max_stake_usd,
            "martingale": bool(config.martingale_enabled),
        },
        "kalshi": {
            "yes_ask": active.get("yes_ask"),
            "yes_bid": active.get("yes_bid"),
            "no_ask": active.get("no_ask"),
            "no_bid": active.get("no_bid"),
            "yes_mid": active.get("yes_mid"),
        },
    }

    # Quant layer (Trackmind): calibrated Kelly only; fat tails size-down
    quant_sizing = {"stake": stake, "mode": "martingale"}
    try:
        from .quant import apply_quant_to_stake

        if config.martingale_enabled and plan.get("mode") == "double_down":
            quant_sizing = {"stake": stake, "mode": "martingale", "note": "martingale owns stake while armed"}
        else:
            quant_sizing = apply_quant_to_stake(stake, j)
            if quant_sizing.get("mode") == "fractional_kelly":
                stake = float(quant_sizing["stake"])
    except Exception as exc:  # noqa: BLE001
        quant_sizing = {"stake": stake, "mode": "error", "error": str(exc)[:120]}

    rec["quant_sizing"] = quant_sizing

    if day_halted():
        rec["result"] = "DAY_STOP"
        rec["reason"] = f"day pnl {day_pnl():.2f} hit stop"
        _append(paths["ledger"], rec)
        return rec

    # Hard risk gate (architecture: if ANY check fails, do not trade)
    risk = j.get("risk") or {}
    if risk.get("blocked"):
        rec["result"] = "RISK_GATE_BLOCK"
        rec["reason"] = "; ".join(risk.get("reasons") or ["risk blocked"])[:240]
        rec["risk"] = risk
        _append(paths["ledger"], rec)
        return rec
    if str(j.get("route") or "").upper() == "ESCALATE" and not config.layer2_enabled:
        rec["result"] = "ESCALATE_NO_LAYER2"
        rec["reason"] = "JEV route=ESCALATE and Layer-2 reasoning not configured"
        _append(paths["ledger"], rec)
        return rec
    if j.get("risk_blocked"):
        rec["result"] = "RISK_GATE_BLOCK"
        rec["reason"] = str(j.get("reason") or "risk blocked")[:240]
        _append(paths["ledger"], rec)
        return rec

    if not ticker:
        rec["result"] = "NO_ACTIVE_MARKET"
        _append(paths["ledger"], rec)
        return rec

    if already_spun(ticker):
        rec["result"] = "ALREADY_SPUN"
        rec["spun"] = True
        return rec

    if stake is not None and stake < 0.05 and plan.get("mode") == "double_down":
        rec["result"] = "SKIP_NO_CASH"
        rec["reason"] = f"stake {stake:.4f} too small / no cash on ex{config.kalshi_exchange_index}"
        _append(paths["ledger"], rec)
        return rec

    side, conf, edge, reason = jev_to_side(j)
    rec["side"] = side
    rec["conf"] = conf
    rec["edge"] = edge
    rec["spin_reason"] = reason

    if side == "SKIP":
        rec["result"] = "SKIP"
        rec["reason"] = reason
        return rec

    if conf < config.conf_floor:
        rec["result"] = "SKIP_CONF"
        rec["reason"] = f"conf {conf:.3f} < {config.conf_floor}"
        _append(paths["ledger"], rec)
        return rec

    if config.edge_floor > 0 and edge < config.edge_floor:
        rec["result"] = "SKIP_EDGE"
        rec["reason"] = f"edge {edge:.3f} < {config.edge_floor}"
        _append(paths["ledger"], rec)
        return rec

    entry = _entry_for(side, active)
    if entry is None:
        rec["result"] = "SKIP_NO_QUOTE"
        rec["reason"] = f"no {side} quote on book"
        _append(paths["ledger"], rec)
        return rec
    # Fill-first martingale: allow high entry when cash can cover 1 contract
    ceil = config.entry_ceil
    if config.martingale_enabled and mode == "LIVE":
        ceil = max(ceil, 0.99)
    if entry > ceil:
        rec["result"] = "SKIP_ENTRY"
        rec["reason"] = f"entry {entry:.4f} > {ceil}"
        _append(paths["ledger"], rec)
        return rec

    cash = plan.get("cash")
    if mode == "LIVE":
        # LIVE: size to at least 1 contract using shard cash (martingale fill mode)
        try:
            from . import martingale as mg
            from . import kalshi_live

            # Prefer cash on the market's crypto shard (usually 2)
            shard_cash = kalshi_live.ensure_shard_funds(
                *kalshi_live.load_creds(),
                dest_shard=int(active.get("exchange_index") or config.kalshi_exchange_index or 2),
                min_dollars=max(0.25, float(stake or 0.25)),
            )
            cash_f = float((shard_cash or {}).get("dest_cash") or cash or 0)
            if cash_f <= 0:
                cash_f = float(mg.kalshi_cash() or 0)
            plan = mg.plan_stake(cash_f)
            # Margin unit: YES ≈ ask; NO ≈ max(yes_bid, 1-yes_bid) short-YES margin
            yb = active.get("yes_bid") if active.get("yes_bid") is not None else active.get("yes_bid_dollars")
            ya = active.get("yes_ask") if active.get("yes_ask") is not None else active.get("yes_ask_dollars")
            try:
                yb = float(yb) if yb not in (None, "") else None
            except (TypeError, ValueError):
                yb = None
            try:
                ya = float(ya) if ya not in (None, "") else None
            except (TypeError, ValueError):
                ya = None
            if side == "YES":
                unit = float(entry or ya or 0.5)
            else:
                unit = max(float(yb or 0.2), 1.0 - float(yb or 0.2)) if yb is not None else float(entry or 0.5)
            wanted = max(float(plan.get("stake") or stake), unit)
            stake = min(cash_f * 0.97, wanted)
            if stake < unit * 0.99:
                other = "NO" if side == "YES" else "YES"
                other_entry = _entry_for(other, active)
                other_unit = float(other_entry or 0.5)
                if other == "NO" and yb is not None:
                    other_unit = max(yb, 1.0 - yb)
                if config.trade_on_lean and other_entry and cash_f >= other_unit:
                    rec["side_switch"] = {"from": side, "to": other, "reason": "affordability"}
                    side = other
                    entry = float(other_entry)
                    unit = other_unit
                    stake = min(cash_f * 0.97, max(unit, float(plan.get("stake") or 0.05)))
            if stake < unit * 0.95:
                rec["result"] = "SKIP_STAKE_TOO_SMALL"
                rec["reason"] = (
                    f"need ~${unit:.2f} for 1 {side} @ {entry:.2f}; "
                    f"stake ${stake:.2f}, shard cash ${cash_f:.2f}"
                )
                rec["shard"] = shard_cash
                _append(paths["ledger"], rec)
                return rec
            rec["stake_bumped"] = {"stake": round(stake, 4), "unit": unit, "entry": entry, "cash": cash_f}
        except Exception as exc:  # noqa: BLE001
            rec["stake_error"] = str(exc)[:200]
    else:
        if entry > 0 and stake < entry and stake < 0.05:
            rec["result"] = "SKIP_STAKE_TOO_SMALL"
            rec["reason"] = f"stake ${stake:.2f} < min contract @ {entry:.2f}"
            _append(paths["ledger"], rec)
            return rec

    rec["entry"] = entry
    rec["side"] = side
    rec["stake_usd"] = stake
    rec["martingale"] = plan

    if mode == "LIVE":
        try:
            from .kalshi_live import place_order

            result = place_order(ticker=ticker, side=side, market=active, stake_usd=stake)
        except Exception as exc:  # noqa: BLE001
            rec["mode"] = "LIVE"
            rec["result"] = "LIVE_ERROR"
            rec["error"] = str(exc)[:400]
            _append(paths["ledger"], rec)
            return rec
        rec["order"] = result
        if result.get("filled"):
            mark_spun(ticker)
            rec["result"] = "LIVE_FILLED"
            rec["filled"] = True
        else:
            rec["result"] = "LIVE_SENT_NO_FILL"
            rec["filled"] = False
        _append(paths["ledger"], rec)
        _touch_scoreboard(rec)
        # refresh martingale cash baseline after attempt
        try:
            from . import martingale as mg

            mg.update_from_cash(mg.kalshi_cash())
        except Exception:  # noqa: BLE001
            pass
        return rec

    # paper
    order = paper_fill(side, entry, stake)
    mark_spun(ticker)
    rec["order"] = order
    rec["filled"] = True
    rec["result"] = "PAPER_FILLED"
    _append(paths["ledger"], rec)
    _touch_scoreboard(rec)
    return rec


def _touch_scoreboard(rec: dict[str, Any]) -> None:
    paths = _paths()
    sb = _load_json(paths["scoreboard"], _empty_scoreboard())
    sb["decisions"] = int(sb.get("decisions") or 0) + 1
    if rec.get("filled"):
        sb["fills"] = int(sb.get("fills") or 0) + 1
        sb["lastFill"] = {
            "ts": rec.get("ts"),
            "ticker": rec.get("ticker"),
            "side": rec.get("side"),
            "entry": rec.get("entry"),
            "mode": rec.get("mode"),
        }
    sb["lastResult"] = rec.get("result")
    sb["lastSide"] = rec.get("side")
    sb["liveArmed"] = live_armed()
    sb["mode"] = rec.get("mode")
    sb["stakeUsd"] = config.stake_usd
    sb["updatedAt"] = int(time.time() * 1000)
    _save_json(paths["scoreboard"], sb)


def recent_tape(limit: int = 24) -> list[dict[str, Any]]:
    path = _paths()["ledger"]
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    rows.reverse()
    return rows
