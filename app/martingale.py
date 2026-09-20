"""Martingale ladder: double-down from a small base until cash >= target, then $2 spins."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .config import config


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path():
    return config.data_dir / "martingale.json"


def load_state() -> dict[str, Any]:
    import json
    p = _state_path()
    if not p.is_file():
        return {
            "mode": "double_down",
            "loss_streak": 0,
            "cash_before": None,
            "target": config.martingale_target,
            "base_stake": config.base_stake_usd,
            "retry_stake": config.retry_stake_usd,
            "updated_at": now_iso(),
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return load_state.__wrapped__() if hasattr(load_state, "__wrapped__") else {
            "mode": "double_down",
            "loss_streak": 0,
            "cash_before": None,
            "target": config.martingale_target,
            "base_stake": config.base_stake_usd,
            "retry_stake": config.retry_stake_usd,
            "updated_at": now_iso(),
        }


def save_state(st: dict[str, Any]) -> None:
    import json
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    st = dict(st)
    st["updated_at"] = now_iso()
    p.write_text(json.dumps(st, indent=2), encoding="utf-8")


def kalshi_cash(exchange_index: int | None = None) -> float | None:
    """Live cash on the exchange shard. None if keys/API unavailable."""
    try:
        from . import kalshi_live
        kid, pk = kalshi_live.load_creds()
        _st, bal = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/balance")
        idx = config.kalshi_exchange_index if exchange_index is None else exchange_index
        for row in bal.get("balance_breakdown") or []:
            try:
                if int(row.get("exchange_index", -1)) == int(idx):
                    return float(row.get("balance") or 0)
            except (TypeError, ValueError):
                continue
        # fallback: total dollars
        return float(bal.get("balance_dollars") or bal.get("balance") or 0) / (
            100.0 if float(bal.get("balance") or 0) > 50 else 1.0
        )
    except Exception:  # noqa: BLE001
        return None


def update_from_cash(cash: float | None) -> dict[str, Any]:
    """Compare cash vs last observation → win/loss streak + mode."""
    st = load_state()
    target = float(config.martingale_target)
    st["target"] = target
    st["base_stake"] = float(config.base_stake_usd)
    st["retry_stake"] = float(config.retry_stake_usd)

    if cash is None:
        st["cash_now"] = None
        return st

    st["cash_now"] = float(cash)
    prev = st.get("cash_before")

    # Target hit → standard $2 mode
    if float(cash) >= target:
        st["mode"] = "standard"
        st["loss_streak"] = 0
        st["cash_before"] = float(cash)
        st["reason"] = f"cash {cash:.2f} >= target {target:.2f} → stake ${config.retry_stake_usd:.2f}"
        save_state(st)
        return st

    st["mode"] = "double_down"

    if prev is None:
        st["cash_before"] = float(cash)
        st["reason"] = "baseline cash recorded"
        save_state(st)
        return st

    delta = float(cash) - float(prev)
    if delta <= -0.005:
        # lost money → next double
        st["loss_streak"] = int(st.get("loss_streak") or 0) + 1
        if st["loss_streak"] > int(config.max_doubles):
            st["loss_streak"] = int(config.max_doubles)
            st["reason"] = f"loss streak capped at {config.max_doubles} (cash {cash:.2f})"
        else:
            st["reason"] = f"loss Δ{delta:.2f} → double step {st['loss_streak']}"
        st["cash_before"] = float(cash)
    elif delta >= 0.005:
        # won / credited → reset ladder
        st["loss_streak"] = 0
        st["reason"] = f"win/credit Δ{delta:+.2f} → reset to base; cash {cash:.2f}/{target:.2f}"
        st["cash_before"] = float(cash)
    else:
        st["reason"] = f"cash unchanged at {cash:.2f} (waiting settle)"

    save_state(st)
    return st


def plan_stake(cash: float | None = None) -> dict[str, Any]:
    """Current stake plan under martingale / standard rules."""
    st = load_state()
    if cash is None:
        cash = st.get("cash_now")
    if cash is not None:
        st = update_from_cash(float(cash))
    cash_f = float(st.get("cash_now") if st.get("cash_now") is not None else (cash or 0.71))

    target = float(config.martingale_target)
    base = float(config.base_stake_usd)
    retry = float(config.retry_stake_usd)
    streak = int(st.get("loss_streak") or 0)
    max_d = int(config.max_doubles)

    # Never spend the whole roll — leave a sliver so a fill can still post
    avail = max(0.0, cash_f * float(config.martingale_reserve_keep))
    # Also respect absolute cash
    hard_cap = max(0.0, cash_f - 0.01)

    if cash_f >= target or st.get("mode") == "standard":
        stake = min(retry, hard_cap) if hard_cap < retry else retry
        # if cash dropped below retry after being "standard", fall back to martingale
        if hard_cap < retry * 0.5:
            mode = "double_down"
            wanted = base * (2 ** streak)
            stake = max(0.05, min(wanted, avail, hard_cap))
        else:
            mode = "standard"
            stake = retry if hard_cap >= retry else max(0.05, hard_cap)
        return {
            "mode": mode,
            "stake": round(stake, 4),
            "cash": cash_f,
            "target": target,
            "loss_streak": streak,
            "base": base,
            "retry_stake": retry,
            "wanted": retry if mode == "standard" else round(base * (2 ** streak), 4),
            "next_double": round(min(base * (2 ** min(streak + 1, max_d + 2)), avail, hard_cap), 4),
            "reason": st.get("reason") or "",
            "armed_target": f"${target:.2f} then ${retry:.2f}/spin",
        }

    wanted = base * (2 ** streak)
    stake = min(wanted, avail, hard_cap)
    if stake < 0.05:
        stake = min(0.05, hard_cap) if hard_cap >= 0.05 else hard_cap

    return {
        "mode": "double_down",
        "stake": round(stake, 4),
        "cash": cash_f,
        "target": target,
        "loss_streak": streak,
        "base": base,
        "retry_stake": retry,
        "wanted": round(wanted, 4),
        "next_double": round(min(wanted * 2, avail, hard_cap), 4),
        "reason": st.get("reason") or f"double-down step {streak} toward ${target:.2f}",
        "armed_target": f"${target:.2f} then ${retry:.2f}/spin",
        "max_doubles": max_d,
    }


def effective_stake() -> float:
    return float(plan_stake().get("stake") or config.base_stake_usd)
