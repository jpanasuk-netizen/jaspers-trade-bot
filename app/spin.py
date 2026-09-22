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


LIVE_ENTRY_RESULTS = {"LIVE_FILLED"}


def is_live_entry(rec: dict[str, Any] | None) -> bool:
    """True only if Kalshi actually filled a live order this row."""
    if not rec:
        return False
    res = str(rec.get("result") or "").upper()
    if res == "LIVE_FILLED":
        return True
    if rec.get("filled") and str(rec.get("mode") or "").upper() == "LIVE":
        return True
    return False


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
    _drop_pending_skip(ticker)


def _pending_skip_path() -> Path:
    return _paths()["ledger"].parent / "pending_skip.json"


def _skipped_windows_path() -> Path:
    return _paths()["ledger"].parent / "skipped_windows.json"


def _skip_logged(ticker: str | None) -> bool:
    if not ticker:
        return False
    data = _load_json(_skipped_windows_path(), {"done": []})
    return ticker in (data.get("done") or [])


def _mark_skip_logged(ticker: str) -> None:
    data = _load_json(_skipped_windows_path(), {"done": []})
    done = data.get("done") or []
    if ticker not in done:
        done.append(ticker)
    data["done"] = done[-200:]
    _save_json(_skipped_windows_path(), data)


def _drop_pending_skip(ticker: str | None = None) -> None:
    path = _pending_skip_path()
    if not path.is_file():
        return
    if ticker is None:
        path.unlink(missing_ok=True)
        return
    pending = _load_json(path, {})
    if pending.get("ticker") == ticker:
        path.unlink(missing_ok=True)


def _flush_pending_skip(current: str | None) -> None:
    """One ledger line for a window that ended without a trade."""
    pending = _load_json(_pending_skip_path(), {})
    prev = str(pending.get("ticker") or "")
    if not prev or prev == (current or ""):
        return
    if already_spun(prev) or _skip_logged(prev):
        _drop_pending_skip(prev)
        return
    rec = dict(pending.get("rec") or {})
    rec["ticker"] = prev
    rec["result"] = rec.get("result") or "SKIP"
    rec["window_skip"] = True
    _mark_skip_logged(prev)
    _append(_paths()["ledger"], rec)
    _drop_pending_skip(prev)


def _commit_pending_skip(ticker: str) -> None:
    """Write the one skip line for a window that is already over."""
    pending = _load_json(_pending_skip_path(), {})
    if str(pending.get("ticker") or "") != ticker:
        return
    if already_spun(ticker) or _skip_logged(ticker):
        _drop_pending_skip(ticker)
        return
    rec = dict(pending.get("rec") or {})
    rec["ticker"] = ticker
    rec["result"] = rec.get("result") or "SKIP"
    rec["window_skip"] = True
    _mark_skip_logged(ticker)
    _append(_paths()["ledger"], rec)
    _drop_pending_skip(ticker)


def _remember_skip(rec: dict[str, Any]) -> None:
    """Hold the latest skip until the window is over. Do not log every poll."""
    ticker = str(rec.get("ticker") or "")
    if not ticker:
        pending = _load_json(_pending_skip_path(), {})
        same = (
            pending.get("ticker") == ""
            and str((pending.get("rec") or {}).get("result") or "") == str(rec.get("result") or "")
        )
        if same:
            return
        _save_json(_pending_skip_path(), {"ticker": "", "rec": rec})
        _append(_paths()["ledger"], rec)
        return
    _flush_pending_skip(ticker)
    if already_spun(ticker) or _skip_logged(ticker):
        return
    _save_json(_pending_skip_path(), {"ticker": ticker, "rec": rec})
    secs = _num(rec.get("seconds_left"))
    if secs is not None and secs <= 0:
        _commit_pending_skip(ticker)


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

    if str(j.get("route") or "").upper() == "SKIP":
        return "SKIP", conf, edge, reason or "jev_route_skip"
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


def _num(v: Any) -> float | None:
    if isinstance(v, dict):
        v = v.get("price") if v.get("price") is not None else v.get("last")
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def tape_side(spot: Any, open_px: Any) -> str | None:
    """YES if BTC is above the window open, NO if below. That is the contract."""
    s = _num(spot)
    o = _num(open_px)
    if s is None or o is None:
        return None
    if s > o:
        return "YES"
    if s < o:
        return "NO"
    return None


def _px_ok(v: Any) -> float | None:
    x = _num(v)
    if x is None or x < 0.01 or x > 0.99:
        return None
    return x


def _book_yes(active: dict[str, Any]) -> float | None:
    """Kalshi's own YES probability. Ignores the 0.001 junk prints."""
    yes_bid = _px_ok(active.get("yes_bid"))
    yes_ask = _px_ok(active.get("yes_ask"))
    no_ask = _px_ok(active.get("no_ask"))
    mid = _px_ok(active.get("yes_mid"))
    if yes_bid is not None and yes_ask is not None:
        return (yes_bid + yes_ask) / 2.0
    if yes_ask is not None and no_ask is not None:
        return yes_ask
    if mid is not None:
        return mid
    return yes_ask


def _lean_band(p: float | None, hi: float = 0.55, lo: float = 0.45) -> str | None:
    if p is None:
        return None
    if p >= hi:
        return "YES"
    if p <= lo:
        return "NO"
    return None


def context_votes(judgment: dict[str, Any] | None, active: dict[str, Any]) -> list[dict[str, str]]:
    """Directional reads already on the desk, besides Jev.

    A missing or undecided feed abstains. It does not invent a side.
    """
    j = judgment or {}
    layer1 = j.get("layer1") or {}
    features = j.get("features") or {}
    micro = j.get("microstructure") or {}
    qd = j.get("quantdinger") or {}
    btcc = j.get("btcc") or {}
    votes: list[dict[str, str]] = []

    book = _lean_band(_book_yes(active))
    if book:
        votes.append({"src": "book", "side": book})

    fair = _lean_band(_num(qd.get("fair_yes")), hi=0.58, lo=0.42)
    if fair is None:
        fair = _lean_band(_num(j.get("fair_yes")), hi=0.58, lo=0.42)
    if fair:
        votes.append({"src": "fair", "side": fair})

    qd_lean = str(qd.get("lean") or "SKIP").upper()
    if qd_lean in {"YES", "NO"}:
        votes.append({"src": "quantdinger", "side": qd_lean})

    btcc_lean = str(btcc.get("lean") or "SKIP").upper()
    btcc_conf = _num(btcc.get("conf")) or 0.0
    if btcc_lean in {"YES", "NO"} and btcc_conf >= 0.55:
        votes.append({"src": "btcc", "side": btcc_lean})

    crowd = str((j.get("ai_trader") or {}).get("lean") or "SKIP").upper()
    if crowd in {"YES", "NO"}:
        votes.append({"src": "ai_trader", "side": crowd})

    ofi = _num(layer1.get("ofi_proxy"))
    if ofi is None:
        ofi = _num(features.get("ofi_proxy"))
    if ofi is not None and ofi >= 0.25:
        votes.append({"src": "ofi", "side": "YES"})
    elif ofi is not None and ofi <= -0.25:
        votes.append({"src": "ofi", "side": "NO"})

    rsi = _num(micro.get("rsi_14"))
    if rsi is None:
        rsi = _num(features.get("rsi_14"))
    if rsi is not None and rsi >= 75:
        votes.append({"src": "rsi", "side": "NO"})
    elif rsi is not None and rsi <= 25:
        votes.append({"src": "rsi", "side": "YES"})

    funding = _num(micro.get("funding_rate_pct"))
    if funding is None:
        funding = _num(features.get("funding_rate_pct"))
    if funding is not None and abs(funding) >= 0.05:
        votes.append({"src": "funding", "side": "NO" if funding > 0 else "YES"})

    polarity = _num(j.get("x_polarity"))
    if polarity is None:
        polarity = _num(j.get("polarity_score"))
    if polarity is not None and abs(polarity) >= 0.35:
        # Same sign as the layer-1 judge: fade a crowded mood.
        votes.append({"src": "sentiment", "side": "NO" if polarity > 0 else "YES"})
    return votes


def live_entry_block(
    side: str,
    active: dict[str, Any],
    seconds_left: Any,
    spot: Any,
    open_px: Any,
    judgment: dict[str, Any] | None = None,
) -> str | None:
    """Why this live side must not be bought. None means it may be quoted.

    If the other desk reads are not lined up against the side, the buy can
    happen at any time the window is still open. The clock does not wait
    for the last three minutes. Tape and the price floor still apply.
    """
    del seconds_left  # window timing is not a gate once the panel passes
    tape = tape_side(spot, open_px)
    if tape and side in {"YES", "NO"} and side != tape:
        return f"side {side} fights the tape ({tape}: spot vs window open). not flipping"
    ask = _entry_for(side, active)
    if ask is not None and ask + 1e-9 < config.entry_floor:
        return (
            f"{side} ask {ask:.3f} < floor {config.entry_floor:.2f} "
            f"(book has already marked this side dead)"
        )
    layer1 = (judgment or {}).get("layer1") or {}
    if layer1.get("regime") == "crisis":
        return "layer1 regime=crisis"
    bocpd = _num(layer1.get("bocpd_alarm"))
    if bocpd is not None and bocpd >= 0.85:
        return f"bocpd alarm {bocpd:.2f} — state just broke"
    if side in {"YES", "NO"}:
        votes = context_votes(judgment, active)
        agrees = [v for v in votes if v["side"] == side]
        disagrees = [v for v in votes if v["side"] != side]
        if disagrees and len(disagrees) > len(agrees):
            against = ", ".join(f"{v['src']}={v['side']}" for v in disagrees)
            with_side = ", ".join(f"{v['src']}={v['side']}" for v in agrees) or "none"
            return f"context disagrees ({against}); with {side}: {with_side}"
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


_EXIT_RESULTS = {"LIVE_SOLD", "LIVE_SELL_NO_FILL", "PAPER_SOLD"}


def open_fill(ticker: str | None) -> dict[str, Any] | None:
    """Latest live fill on this ticker that has not already been sold."""
    if not ticker:
        return None
    path = _paths()["ledger"]
    if not path.is_file():
        return None
    held: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if str(rec.get("ticker") or "") != ticker:
            continue
        res = str(rec.get("result") or "")
        if res == "LIVE_FILLED" and rec.get("filled"):
            held = rec
        elif res in _EXIT_RESULTS:
            held = None
    return held


def _exit_bid(side: str, active: dict[str, Any]) -> float | None:
    """Cash we can get back per contract, right now."""
    if side == "YES":
        return _num(active.get("yes_bid"))
    bid = _num(active.get("no_bid"))
    if bid is not None and 0.01 <= bid <= 0.99:
        return bid
    ask = _num(active.get("yes_ask"))
    if ask is not None and 0.01 <= ask <= 0.99:
        return round(1.0 - ask, 4)
    return None


def salvage_reason(
    side: str,
    entry: Any,
    bid: float | None,
    spot: Any,
    open_px: Any,
    judgment: dict[str, Any] | None,
    active: dict[str, Any],
    seconds_left: Any,
) -> str | None:
    """Why an open ticket should be sold before settlement. None means hold.

    One noisy tick is not enough. The tape has to flip and something else
    (the book, the panel, or a collapsed bid) has to agree we are the loser,
    and the bid still has to pay at least 5 cents.
    """
    secs = _num(seconds_left)
    if secs is not None and secs <= 8:
        return None
    if bid is None or bid < 0.05 or bid > 0.99:
        return None
    paid = _num(entry)
    marks: list[str] = []
    tape = tape_side(spot, open_px)
    if tape and tape != side:
        marks.append(f"tape flipped to {tape}")
    fair = _book_yes(active)
    if fair is not None:
        ours = fair if side == "YES" else 1.0 - fair
        if ours <= 0.42:
            marks.append(f"book marks {side} at {ours:.2f}")
    votes = context_votes(judgment, active)
    oppose = [v for v in votes if v["side"] != side]
    agree = [v for v in votes if v["side"] == side]
    if oppose and len(oppose) > len(agree):
        marks.append("panel flipped to " + ",".join(f"{v['src']}={v['side']}" for v in oppose))
    if paid is not None and bid + 0.12 < paid:
        marks.append(f"bid {bid:.2f} is below entry {paid:.2f}")
    flipped = any(m.startswith("tape flipped") for m in marks)
    if flipped and len(marks) >= 2:
        return "salvage: " + "; ".join(marks)
    if len(marks) >= 3:
        return "salvage: " + "; ".join(marks)
    return None


def _maybe_salvage(
    rec: dict[str, Any],
    judgment: dict[str, Any],
    active: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any] | None:
    """Sell the open ticket when the window has turned against it. One try."""
    ticker = str(rec.get("ticker") or "")
    held = open_fill(ticker)
    if not held:
        return None
    side = str(held.get("side") or "").upper()
    if side not in {"YES", "NO"}:
        return None
    count = _contract_count(held)
    bid = _exit_bid(side, active)
    why = salvage_reason(
        side,
        held.get("entry"),
        bid,
        rec.get("spot"),
        rec.get("open_of_window"),
        judgment,
        active,
        rec.get("seconds_left"),
    )
    if not why or count < 0.01:
        return None
    rec["strategy"] = "salvage"
    rec["side"] = side
    rec["entry"] = held.get("entry")
    rec["count"] = count
    rec["exit_bid"] = bid
    rec["reason"] = why
    try:
        from .kalshi_live import close_position

        result = close_position(ticker, side, count, active)
    except Exception as exc:  # noqa: BLE001
        rec["result"] = "LIVE_SELL_NO_FILL"
        rec["error"] = str(exc)[:400]
        _append(paths["ledger"], rec)
        return rec
    rec["live"] = {
        k: result.get(k)
        for k in ("filled", "fill_count", "price", "book_side", "count", "error", "http_status")
        if k in result
    }
    rec["filled"] = bool(result.get("filled"))
    rec["result"] = "LIVE_SOLD" if rec["filled"] else "LIVE_SELL_NO_FILL"
    rec["spin_reason"] = (
        f"sold {count} {side} at bid {bid} — {why}"
        if rec["filled"]
        else f"sell missed {count} {side} bid {bid} — {why}"
    )
    _append(paths["ledger"], rec)
    _touch_scoreboard(rec)
    return rec


def _contract_count(rec: dict[str, Any]) -> float:
    for src in (rec.get("live"), rec.get("quote"), rec.get("order")):
        if not isinstance(src, dict):
            continue
        for key in ("fill_count", "count"):
            try:
                n = float(src.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if n > 0:
                return n
    try:
        entry = float(rec.get("entry") or 0)
        cost = float(rec.get("stake_usd") or 0)
    except (TypeError, ValueError):
        return 0.0
    if entry > 0 and cost > 0:
        return cost / entry
    return 0.0


def fill_pnl(rec: dict[str, Any], won: bool) -> float:
    """Settlement profit for one filled ticket. Cost is stake_usd; a win pays $1 per contract."""
    try:
        cost = float(rec.get("stake_usd") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if won:
        return round(_contract_count(rec) - cost, 4)
    return round(-cost, 4)


_OPEN_SETTLE_UNTIL: dict[str, float] = {}


def settle_and_update_scoreboard() -> dict[str, Any]:
    """Recount fills from the ledger. Wins and losses come from Kalshi settlement."""
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
    from .settle import attach_outcome

    wins = losses = 0
    pnl = 0.0
    now = time.time()
    for rec in trades:
        ticker = str(rec.get("ticker") or "")
        if ticker and _OPEN_SETTLE_UNTIL.get(ticker, 0) > now:
            continue
        settled = attach_outcome(rec)
        won = settled.get("won")
        if won is None:
            if ticker:
                _OPEN_SETTLE_UNTIL[ticker] = now + 30.0
            continue
        if won:
            wins += 1
        else:
            losses += 1
        pnl += fill_pnl(rec, bool(won))
    sb = _load_json(paths["scoreboard"], _empty_scoreboard())
    sb["decisions"] = sb.get("decisions", 0)
    sb["fills"] = len(trades)
    sb["pnlUsd"] = round(pnl, 4)
    sb["wins"] = wins
    sb["losses"] = losses
    sb["pushes"] = 0
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
            "model": j.get("model") or j.get("model_pinned"),
            "blueprint": "RohOnChain/2101311813908652069",
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
                from .argus_gate import promotion_report

                report = promotion_report()
                quant_sizing["argus"] = {
                    "promote": report.get("promote"),
                    "reason": report.get("reason"),
                }
                if report.get("promote"):
                    stake = float(quant_sizing["stake"])
                else:
                    quant_sizing["mode"] = "argus_hold"
                    quant_sizing["note"] = report.get("reason")
    except Exception as exc:  # noqa: BLE001
        quant_sizing = {"stake": stake, "mode": "error", "error": str(exc)[:120]}

    rec["quant_sizing"] = quant_sizing
    try:
        from .argus_gate import promotion_report

        rep = promotion_report()
        rec["argus"] = {"promote": bool(rep.get("promote")), "reason": rep.get("reason"), "n": rep.get("n")}
    except Exception as exc:  # noqa: BLE001
        rec["argus"] = {"promote": False, "reason": str(exc)[:160]}

    # Hold the original ticket. The two live salvages both sold a YES that
    # then settled YES, so selling the stake gave back a winner.
    if day_halted():
        rec["result"] = "DAY_STOP"
        rec["reason"] = f"day pnl {day_pnl():.2f} hit stop"
        _remember_skip(rec)
        return rec

    # Hard risk gate (architecture: if ANY check fails, do not trade)
    risk = j.get("risk") or {}
    if risk.get("blocked"):
        rec["result"] = "RISK_GATE_BLOCK"
        rec["reason"] = "; ".join(risk.get("reasons") or ["risk blocked"])[:240]
        rec["risk"] = risk
        _remember_skip(rec)
        return rec
    if str(j.get("route") or "").upper() == "ESCALATE" and not config.layer2_enabled:
        rec["result"] = "ESCALATE_NO_LAYER2"
        rec["reason"] = "JEV route=ESCALATE and Layer-2 reasoning not configured"
        _remember_skip(rec)
        return rec
    if j.get("risk_blocked"):
        rec["result"] = "RISK_GATE_BLOCK"
        rec["reason"] = str(j.get("reason") or "risk blocked")[:240]
        _remember_skip(rec)
        return rec

    if not ticker:
        rec["result"] = "NO_ACTIVE_MARKET"
        _append(paths["ledger"], rec)
        return rec

    _flush_pending_skip(ticker)

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
        # Penny-Jev: $0.04 can only buy a 1–3¢ ask. That print is almost never
        # the spot-vs-open favorite. Old recover waited for the favorite to get
        # cheap (SKIP_NO_EDGE forever). New rule: buy Jev's side only, 1-lot,
        # if we can actually pay. If Jev's side is 90¢, wait. Never buy the
        # dying side just because it's the only affordable ticket.
        try:
            from . import kalshi_live

            shard_cash = kalshi_live.ensure_shard_funds(
                *kalshi_live.load_creds(),
                dest_shard=int(active.get("exchange_index") or config.kalshi_exchange_index or 0),
                min_dollars=0.04,
            )
            cash_f = float((shard_cash or {}).get("dest_cash") or cash_now or 0)
            try:
                from . import martingale as mg

                pred = float(mg.kalshi_cash() or 0)
                if pred > cash_f:
                    cash_f = pred
            except Exception:  # noqa: BLE001
                pass
            jev_side, jev_conf, _jev_edge, jev_why = jev_to_side(j)
            rec["strategy"] = "penny_jev"
            rec["jev_side"] = jev_side
            rec["jev_conf"] = jev_conf
            if jev_side not in {"YES", "NO"}:
                rec["result"] = "SKIP_NO_EDGE"
                rec["reason"] = f"penny_jev: Jev did not fire ({jev_why or 'SKIP'}) cash ${cash_f:.4f}"
                rec["shard"] = shard_cash
                _remember_skip(rec)
                return rec
            if jev_conf < config.conf_floor:
                rec["result"] = "SKIP_CONF"
                rec["reason"] = f"penny_jev: conf {jev_conf:.3f} < {config.conf_floor} side={jev_side}"
                rec["shard"] = shard_cash
                _remember_skip(rec)
                return rec
            pick = kalshi_live.sized_quote(jev_side, active, cash_f, max_count=1.0)
            one = kalshi_live.contract_quote(jev_side, active)
            if one and float(one.get("ask") or 1) > config.entry_ceil + 1e-9:
                rec["result"] = "SKIP_ENTRY"
                rec["reason"] = (
                    f"penny_jev: {jev_side} ask {one.get('ask')} > {config.entry_ceil:.2f}"
                )
                rec["quote"] = one
                rec["shard"] = shard_cash
                _remember_skip(rec)
                return rec
            if pick and cash_f + 1e-9 >= pick["need"]:
                rec["recover_fire"] = True
                rec["side"] = pick["side"]
                rec["entry"] = pick["ask"]
                rec["stake_usd"] = pick["need"]
                rec["win_pay"] = round(1.0 - float(pick["ask"]), 4)
                rec["conf"] = jev_conf
                rec["spin_reason"] = (
                    f"penny_jev {pick['count']} {pick['side']} @ {pick['ask']:.2f}+fee {pick['fee']:.2f} "
                    f"= ${pick['need']:.2f} cash ${cash_f:.4f} jev_conf={jev_conf:.2f}"
                )
                rec["quote"] = pick
                rec["shard"] = shard_cash
                rec["mode"] = "LIVE"
                try:
                    result = kalshi_live.place_order(
                        ticker=ticker,
                        side=pick["side"],
                        market=active,
                        stake_usd=pick["need"],
                        count=float(pick["count"]),
                    )
                except Exception as exc:  # noqa: BLE001
                    rec["result"] = "LIVE_ERROR"
                    rec["error"] = str(exc)[:400]
                    mark_spun(ticker)
                    _append(paths["ledger"], rec)
                    _touch_scoreboard(rec)
                    return rec
                rec["live"] = {
                    k: result.get(k)
                    for k in ("filled", "fill_count", "price", "book_side", "count", "est_cost", "error", "http_status")
                    if k in result
                }
                rec["filled"] = bool(result.get("filled")) or float(result.get("fill_count") or 0) > 0
                rec["result"] = "LIVE_FILLED" if rec["filled"] else "LIVE_SENT_NO_FILL"
                mark_spun(ticker)
                if rec["filled"]:
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
                f"penny_jev wait: Jev={jev_side} (YES or NO) conf={jev_conf:.2f} "
                f"cash ${cash_f:.4f} cannot size even 0.01 of {jev_side} @ {src.get('ask')} "
                f"(1-lot need ${src.get('need')})."
            )
            rec["quote"] = src
            rec["shard"] = shard_cash
            _remember_skip(rec)
            return rec
        except Exception as exc:  # noqa: BLE001
            rec["recover_error"] = str(exc)[:240]
            # fall through to normal path

    if stake is not None and stake < 0.01 and plan.get("mode") == "double_down":
        rec["result"] = "SKIP_NO_CASH"
        rec["reason"] = f"stake {stake:.4f} too small / no cash on ex{config.kalshi_exchange_index}"
        _remember_skip(rec)
        return rec

    side, conf, edge, reason = jev_to_side(j)
    rec["side"] = side
    rec["conf"] = conf
    rec["edge"] = edge
    rec["spin_reason"] = reason

    if side == "SKIP":
        rec["result"] = "SKIP"
        rec["reason"] = reason
        _remember_skip(rec)
        return rec

    if conf < config.conf_floor:
        rec["result"] = "SKIP_CONF"
        rec["reason"] = f"conf {conf:.3f} < {config.conf_floor}"
        _remember_skip(rec)
        return rec

    if config.edge_floor > 0 and edge < config.edge_floor:
        rec["result"] = "SKIP_EDGE"
        rec["reason"] = f"edge {edge:.3f} < {config.edge_floor}"
        _remember_skip(rec)
        return rec

    entry = _entry_for(side, active)
    if entry is None:
        rec["result"] = "SKIP_NO_QUOTE"
        rec["reason"] = f"no {side} quote on book"
        _remember_skip(rec)
        return rec
    if entry > config.entry_ceil + 1e-9:
        rec["result"] = "SKIP_ENTRY"
        rec["reason"] = f"entry {entry:.4f} > {config.entry_ceil:.2f}"
        _remember_skip(rec)
        return rec

    cash = plan.get("cash")
    if mode == "LIVE":
        # LIVE pennies: 1-lot = the ASK + Kalshi 1¢-style fee. Not short-YES margin.
        try:
            from . import martingale as mg
            from . import kalshi_live

            shard_cash = kalshi_live.ensure_shard_funds(
                *kalshi_live.load_creds(),
                dest_shard=int(active.get("exchange_index") or config.kalshi_exchange_index or 0),
                min_dollars=0.04,
            )
            cash_f = float((shard_cash or {}).get("dest_cash") or cash or 0)
            if cash_f <= 0:
                cash_f = float(mg.kalshi_cash() or 0)
            plan = mg.plan_stake(cash_f)
            q = kalshi_live.contract_quote(side, active)
            if q and cash_f + 1e-9 >= q["need"]:
                pick = q
            else:
                src = q or {}
                need = src.get("need")
                ask = src.get("ask")
                fee = src.get("fee")
                win_pay = round(1.0 - float(ask), 4) if ask is not None else None
                rec["result"] = "SKIP_WIN_TOO_SMALL"
                rec["reason"] = (
                    f"not flipping off {side}. "
                    f"1-lot {side} @ {ask if ask is not None else '—'} "
                    f"+fee {fee if fee is not None else '—'} "
                    f"needs ${need if need is not None else '—'}, cash ${cash_f:.4f}. "
                    f"The cheaper opposite side is how the last flips lost."
                )
                rec["shard"] = shard_cash
                rec["quote"] = src
                rec["win_pay"] = win_pay
                _remember_skip(rec)
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
            _remember_skip(rec)
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
            mark_spun(ticker)
            _append(paths["ledger"], rec)
            return rec
        rec["order"] = result
        if result.get("filled"):
            rec["result"] = "LIVE_FILLED"
            rec["filled"] = True
        else:
            rec["result"] = "LIVE_SENT_NO_FILL"
            rec["filled"] = False
        mark_spun(ticker)
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
