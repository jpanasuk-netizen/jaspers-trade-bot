"""Climb ladder: keep doubling the last filled stake until cash >= $6, then $2 spins.

Win below target → press (do not reset to 5¢).
Loss → double again, capped at remaining cash.
No 4-step cap. Pennies are rung 0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import config


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path():
    return config.data_dir / "martingale.json"


def _blank() -> dict[str, Any]:
    return {
        "mode": "double_down",
        "loss_streak": 0,
        "win_streak": 0,
        "rung": 0,
        "last_stake": None,
        "cash_before": None,
        "cash_now": None,
        "target": config.martingale_target,
        "base_stake": config.base_stake_usd,
        "retry_stake": config.retry_stake_usd,
        "updated_at": now_iso(),
    }


def load_state() -> dict[str, Any]:
    import json

    p = _state_path()
    if not p.is_file():
        return _blank()
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return _blank()
    if not isinstance(st, dict):
        return _blank()
    st.setdefault("rung", 0)
    st.setdefault("win_streak", 0)
    st.setdefault("last_stake", None)
    return st


def save_state(st: dict[str, Any]) -> dict[str, Any]:
    import json

    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    st = dict(st)
    st["updated_at"] = now_iso()
    p.write_text(json.dumps(st, indent=2), encoding="utf-8")
    return st


def kalshi_cash(exchange_index: int | None = None) -> float | None:
    """Live Predictions cash. Default = event-contract wallet (UI Predictions)."""
    try:
        from . import kalshi_live

        kid, pk = kalshi_live.load_creds()
        _st, bal = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/balance")
        if exchange_index is not None:
            idx = int(exchange_index)
            for row in bal.get("balance_breakdown") or []:
                try:
                    if int(row.get("exchange_index", -1)) == idx:
                        return float(row.get("balance") or 0)
                except (TypeError, ValueError):
                    continue
        # Predictions = event shards 0 + 2 (not perps). Matches Kalshi UI.
        pred = 0.0
        saw = False
        for row in bal.get("balance_breakdown") or []:
            try:
                idx = int(row.get("exchange_index", -1))
            except (TypeError, ValueError):
                continue
            if idx in (0, 2):
                pred += float(row.get("balance") or 0)
                saw = True
        if saw:
            return round(pred, 4)
        raw = float(bal.get("balance_dollars") or bal.get("balance") or 0)
        return raw / 100.0 if raw > 50 else raw
    except Exception:  # noqa: BLE001
        return None


def note_fill(stake: float, cash_after: float | None = None) -> dict[str, Any]:
    """Record a real fill so the next rung is 2× this stake."""
    st = load_state()
    st["last_stake"] = round(float(stake), 4)
    st["rung"] = int(st.get("rung") or 0) + 1
    if cash_after is not None:
        st["cash_now"] = float(cash_after)
    st["reason"] = f"filled ${stake:.4f} → next double ${float(stake) * 2:.4f} until ${config.martingale_target:.2f}"
    return save_state(st)


def update_from_cash(cash: float | None) -> dict[str, Any]:
    """Compare cash vs last observation → win/loss + keep doubling until $6."""
    st = load_state()
    target = float(config.martingale_target)
    st["target"] = target
    st["base_stake"] = float(config.base_stake_usd)
    st["retry_stake"] = float(config.retry_stake_usd)

    if cash is None:
        st["cash_now"] = None
        return st

    cash_f = float(cash)
    st["cash_now"] = cash_f
    prev = st.get("cash_before")

    if cash_f >= target:
        st["mode"] = "standard"
        st["loss_streak"] = 0
        st["win_streak"] = 0
        st["rung"] = 0
        st["last_stake"] = None
        st["cash_before"] = cash_f
        st["reason"] = f"cash {cash_f:.2f} >= target {target:.2f} → ${config.retry_stake_usd:.2f}/spin"
        return save_state(st)

    st["mode"] = "double_down"

    if prev is None:
        st["cash_before"] = cash_f
        st["reason"] = f"baseline ${cash_f:.4f} — double until ${target:.2f}"
        return save_state(st)

    delta = cash_f - float(prev)
    last = float(st.get("last_stake") or 0)
    if delta <= -0.005:
        st["loss_streak"] = int(st.get("loss_streak") or 0) + 1
        st["win_streak"] = 0
        nxt = last * 2 if last > 0 else cash_f
        st["reason"] = f"loss Δ{delta:.4f} → double to ${nxt:.4f} (cash {cash_f:.4f}/{target:.2f})"
        st["cash_before"] = cash_f
    elif delta >= 0.005:
        st["win_streak"] = int(st.get("win_streak") or 0) + 1
        st["loss_streak"] = 0
        nxt = last * 2 if last > 0 else cash_f
        st["reason"] = (
            f"win Δ{delta:+.4f} — press, do not reset. "
            f"next ${nxt:.4f} until ${target:.2f} (cash {cash_f:.4f})"
        )
        st["cash_before"] = cash_f
    else:
        st["reason"] = f"cash unchanged at {cash_f:.4f} (waiting settle / ${target:.2f})"

    return save_state(st)


def plan_stake(cash: float | None = None) -> dict[str, Any]:
    """Current stake plan: 2× last fill until $6, else $2 clips."""
    st = load_state()
    if cash is None:
        cash = st.get("cash_now")
    if cash is not None:
        st = update_from_cash(float(cash))
    cash_f = float(st.get("cash_now") if st.get("cash_now") is not None else (cash or 0.0))

    target = float(config.martingale_target)
    base = float(config.base_stake_usd)
    retry = float(config.retry_stake_usd)
    last = st.get("last_stake")
    last_f = float(last) if last not in (None, "") else 0.0
    avail = max(0.0, cash_f * float(config.martingale_reserve_keep))
    hard_cap = max(0.0, cash_f - 0.01)

    if cash_f >= target:
        stake = min(retry, hard_cap) if hard_cap > 0 else 0.0
        if hard_cap < retry * 0.5:
            mode = "double_down"
            wanted = last_f * 2 if last_f > 0 else max(base, cash_f)
            stake = min(wanted, avail, hard_cap)
        else:
            mode = "standard"
            wanted = retry
        return {
            "mode": mode,
            "stake": round(max(0.0, stake), 4),
            "cash": cash_f,
            "target": target,
            "loss_streak": int(st.get("loss_streak") or 0),
            "win_streak": int(st.get("win_streak") or 0),
            "rung": int(st.get("rung") or 0),
            "last_stake": last_f or None,
            "base": base,
            "retry_stake": retry,
            "wanted": round(wanted, 4),
            "next_double": round(min((last_f * 2 if last_f else stake * 2), hard_cap), 4),
            "reason": st.get("reason") or "",
            "armed_target": f"double until ${target:.2f} then ${retry:.2f}/spin",
        }

    # Climb: first rung = all pennies; every later rung = 2× last fill, capped at cash.
    if last_f > 0:
        wanted = last_f * 2.0
    else:
        wanted = hard_cap if hard_cap > 0 else cash_f
    stake = min(wanted, avail, hard_cap)
    if stake < 0.01:
        stake = hard_cap

    return {
        "mode": "double_down",
        "stake": round(max(0.0, stake), 4),
        "cash": cash_f,
        "target": target,
        "loss_streak": int(st.get("loss_streak") or 0),
        "win_streak": int(st.get("win_streak") or 0),
        "rung": int(st.get("rung") or 0),
        "last_stake": last_f or None,
        "base": base,
        "retry_stake": retry,
        "wanted": round(wanted, 4),
        "next_double": round(min(max(stake, last_f) * 2.0, hard_cap), 4),
        "reason": st.get("reason") or f"double until ${target:.2f}",
        "armed_target": f"double until ${target:.2f} then ${retry:.2f}/spin",
    }


def effective_stake() -> float:
    return float(plan_stake().get("stake") or config.base_stake_usd)
