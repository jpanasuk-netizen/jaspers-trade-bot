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
    count = max(1, int(stake / max(0.01, px)))
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

    cash_now = float(plan.get("cash") or 0)
    target = float(plan.get("target") or config.martingale_target)
    recover = bool(
        mode == "LIVE"
        and config.martingale_enabled
        and cash_now > 0
        and cash_now < target
    )

    if recover:
        # Pennies-back: buy the cheapest 1-lot we can actually pay. Judge SKIP
        # / conf floor do not sit on 3¢ — that's how we climb to $6.
        try:
            from . import kalshi_live

            shard_cash = kalshi_live.ensure_shard_funds(
                *kalshi_live.load_creds(),
                dest_shard=int(active.get("exchange_index") or config.kalshi_exchange_index or 2),
                min_dollars=0.04,
            )
            cash_f = float((shard_cash or {}).get("dest_cash") or cash_now or 0)
            pick = kalshi_live.cheapest_affordable(active, cash_f)
            # Only the side that can pay: YES if spot is above open, NO if below.
            spot = j.get("spot")
            open_px = j.get("open_of_window") or active.get("open_of_window")
            fair = None
            try:
                fair = float((j.get("quantdinger") or {}).get("fair_yes") or j.get("fair_yes") or 0)
                if fair <= 0:
                    fair = None
            except (TypeError, ValueError):
                fair = None
            lead = None
            if fair is not None:
                lead = "YES" if fair >= 0.55 else ("NO" if fair <= 0.45 else None)
            if lead is None and spot is not None and open_px:
                try:
                    lead = "YES" if float(spot) > float(open_px) else "NO"
                except (TypeError, ValueError):
                    lead = None
            if pick and lead and pick["side"] != lead:
                rec["result"] = "SKIP_NO_EDGE"
                rec["reason"] = (
                    f"cheap {pick['side']} @ {pick['ask']} is the dying side. "
                    f"lead={lead} fair={fair} spot={spot} open={open_px}. "
                    f"wait for the winning side to get cheap enough to buy."
                )
                rec["quote"] = pick
                rec["lead"] = lead
                _append(paths["ledger"], rec)
                return rec
            if pick and cash_f + 1e-9 >= pick["need"] and (lead is None or pick["side"] == lead):
                rec["recover_fire"] = True
                rec["side"] = pick["side"]
                rec["entry"] = pick["ask"]
                rec["stake_usd"] = pick["need"]
                rec["win_pay"] = round(1.0 - float(pick["ask"]), 4)
                rec["conf"] = rec.get("conf")
                rec["spin_reason"] = (
                    f"recover 1-lot {pick['side']} @ {pick['ask']:.2f}+fee {pick['fee']:.2f} "
                    f"= ${pick['need']:.2f} (win ${1-pick['ask']:.2f}) cash ${cash_f:.4f}"
                )
                rec["quote"] = pick
                rec["shard"] = shard_cash
                rec["mode"] = "LIVE"
                try:
                    result = kalshi_live.place_order(
                        ticker=ticker, side=pick["side"], market=active, stake_usd=pick["need"]
                    )
                except Exception as exc:  # noqa: BLE001
                    rec["result"] = "LIVE_ERROR"
                    rec["error"] = str(exc)[:400]
                    _append(paths["ledger"], rec)
                    _touch_scoreboard(rec)
                    return rec
                rec["live"] = {
                    k: result.get(k)
                    for k in ("filled", "fill_count", "price", "book_side", "count", "est_cost", "error")
                    if k in result
                }
                rec["filled"] = bool(result.get("filled"))
                rec["result"] = "LIVE_FILLED" if rec["filled"] else "LIVE_SENT_NO_FILL"
                if rec["filled"]:
                    mark_spun(ticker)
                    try:
                        from . import martingale as mg

                        mg.note_fill(float(pick["need"]), mg.kalshi_cash())
                    except Exception:  # noqa: BLE001
                        pass
                _append(paths["ledger"], rec)
                _touch_scoreboard(rec)
                return rec
            src = pick or {}
            rec["result"] = "SKIP_WIN_TOO_SMALL"
            rec["reason"] = (
                f"pennies ready (${cash_f:.4f}) but no 1-lot we can buy. "
                f"cheapest {src.get('side')} @ {src.get('ask')} need ${src.get('need')}."
            )
            rec["quote"] = src
            rec["shard"] = shard_cash
            _append(paths["ledger"], rec)
            return rec
        except Exception as exc:  # noqa: BLE001
            rec["recover_error"] = str(exc)[:240]
            # fall through to normal path

    if stake is not None and stake < 0.01 and plan.get("mode") == "double_down":
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
        # LIVE pennies: 1-lot = the ASK + Kalshi 1¢-style fee. Not short-YES margin.
        try:
            from . import martingale as mg
            from . import kalshi_live

            shard_cash = kalshi_live.ensure_shard_funds(
                *kalshi_live.load_creds(),
                dest_shard=int(active.get("exchange_index") or config.kalshi_exchange_index or 2),
                min_dollars=0.04,
            )
            cash_f = float((shard_cash or {}).get("dest_cash") or cash or 0)
            if cash_f <= 0:
                cash_f = float(mg.kalshi_cash() or 0)
            plan = mg.plan_stake(cash_f)
            q = kalshi_live.contract_quote(side, active)
            cheap = kalshi_live.cheapest_affordable(active, cash_f)
            if q and cash_f + 1e-9 >= q["need"]:
                pick = q
            elif cheap and cash_f + 1e-9 >= cheap["need"]:
                if cheap["side"] != side:
                    rec["side_switch"] = {
                        "from": side,
                        "to": cheap["side"],
                        "reason": f"pennies buy {cheap['side']} @ {cheap['ask']:.2f}+{cheap['fee']:.2f}",
                    }
                pick = cheap
                side = cheap["side"]
            else:
                src = cheap or q or {}
                need = src.get("need")
                ask = src.get("ask")
                fee = src.get("fee")
                sside = src.get("side") or side
                win_pay = round(1.0 - float(ask), 4) if ask is not None else None
                rec["result"] = "SKIP_WIN_TOO_SMALL"
                rec["reason"] = (
                    f"3¢ stake is fine — the printed win isn't. "
                    f"Cheapest 1-lot {sside} @ {ask if ask is not None else '—'} "
                    f"pays ${win_pay if win_pay is not None else '—'} if right "
                    f"(need ${need if need is not None else '—'}, cash ${cash_f:.4f}). "
                    f"Wait for a ≤3¢ ask (win ≥97¢)."
                )
                rec["shard"] = shard_cash
                rec["quote"] = src
                rec["win_pay"] = win_pay
                _append(paths["ledger"], rec)
                return rec
            entry = float(pick["ask"])
            stake = float(pick["need"])
            rec["win_pay"] = round(1.0 - entry, 4)
            lot = float(pick["need"])
            wanted = float(plan.get("stake") or lot)
            lots = max(1, int(wanted / lot)) if lot > 0 else 1
            while lots > 1 and lots * lot > cash_f + 1e-9:
                lots -= 1
            stake = round(lots * lot, 4)
            rec["stake_bumped"] = {
                "stake": stake,
                "unit": pick["unit"],
                "fee": pick["fee"],
                "need": pick["need"],
                "lots": lots,
                "wanted": round(wanted, 4),
                "entry": entry,
                "cash": cash_f,
                "side": side,
                "win_pay": rec["win_pay"],
                "next_double": round(stake * 2, 4),
            }
        except Exception as exc:  # noqa: BLE001
            rec["stake_error"] = str(exc)[:200]
    else:
        if entry > 0 and stake < entry and stake < 0.05:
            rec["result"] = "SKIP_WIN_TOO_SMALL"
            rec["reason"] = (
                f"3¢ stake is fine — ticket @ {entry:.2f} pays ${1-entry:.2f}; "
                f"need ${entry:.2f}, stake ${stake:.2f}. Wait for a ≤3¢ ask."
            )
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
        try:
            from . import martingale as mg

            cash_now = mg.kalshi_cash()
            if rec.get("filled"):
                mg.note_fill(float(rec.get("stake_usd") or stake), cash_now)
            mg.update_from_cash(cash_now)
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
    return history_records(limit)


def history_records(limit: int = 250) -> list[dict[str, Any]]:
    path = _paths()["ledger"]
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit)) :]:
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    rows.reverse()
    return rows


def history_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fills = sent = skips = errors = 0
    windows: set[str] = set()
    for r in rows:
        res = str(r.get("result") or "")
        if res in {"LIVE_FILLED", "PAPER_FILLED"}:
            fills += 1
        elif res in {"LIVE_SENT_NO_FILL"}:
            sent += 1
        elif res.startswith("SKIP") or res in {"RISK_GATE_BLOCK", "ALREADY_SPUN", "DAY_STOP", "ESCALATE_NO_LAYER2"}:
            skips += 1
        elif "ERROR" in res:
            errors += 1
        t = r.get("ticker")
        if t:
            windows.add(str(t))
    return {
        "fills": fills,
        "sentNoFill": sent,
        "skips": skips,
        "errors": errors,
        "windows": len(windows),
        "n": len(rows),
    }
