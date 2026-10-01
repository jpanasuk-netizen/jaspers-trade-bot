"""Miles operating notes: ledger, learnings, and scheduled reviews.

Writes markdown under data/. Does not edit config, .env, or orders.
A single trade never changes the live rules.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import config


def _dir() -> Path:
    path = config.data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_fills() -> list[dict[str, Any]]:
    ledger = config.data_dir / "spin_ledger.jsonl"
    if not ledger.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("mode") in {"PAPER", "LIVE"} and rec.get("filled"):
            rows.append(rec)
    return rows


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _settled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .settle import attach_outcome
    from .spin import fill_pnl

    out: list[dict[str, Any]] = []
    for rec in rows:
        settled = attach_outcome(rec)
        if settled.get("won") is None:
            settled["pnl"] = None
        else:
            settled["pnl"] = fill_pnl(rec, bool(settled["won"]))
        out.append(settled)
    return out


def _write(name: str, text: str) -> None:
    (_dir() / name).write_text(text, encoding="utf-8")


def _context() -> str:
    target = float(config.martingale_target or 6.0)
    return "\n".join([
        "# Trading context",
        "",
        "Kalshi BTC 15-minute up/down only (KXBTC15M). YES means Bitcoin finishes the window above the open.",
        "Jev names the side. The desk does not flip to the cheaper side.",
        f"Buy that side only at or under {float(config.entry_ceil):.2f}.",
        f"While cash is under ${target:.0f}, each live order spends the configured clip, fee included — not the whole balance.",
        f"At ${target:.0f} and above, the live clip is ${float(config.order_budget_usd):.2f} (or the regime size, whichever is smaller).",
        "A sharp BTC spike lets Jev fire before the last three minutes. Fade/follow shadows stay paper.",
        "An open ticket is sold only when the other side is priced above 80%.",
        "One try per window. A day of settled losses can sit the desk down.",
        "These notes record what happened. They do not change the live rules after one trade.",
        "",
    ])


def _ledger_md(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Trade ledger",
        "",
        "| time | ticker | side | entry | size | result | pnl | why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rec in rows[-80:]:
        won = rec.get("won")
        result = "open" if won is None else ("win" if won else "loss")
        pnl = rec.get("pnl")
        pnl_s = "" if pnl is None else f"{pnl:.2f}"
        why = str(rec.get("spin_reason") or rec.get("reason") or "").replace("|", "/")[:80]
        lines.append(
            "| {ts} | {ticker} | {side} | {entry} | {size} | {result} | {pnl} | {why} |".format(
                ts=str(rec.get("ts") or "")[:19],
                ticker=rec.get("ticker") or "",
                side=rec.get("side") or "",
                entry=rec.get("entry") if rec.get("entry") is not None else "",
                size=rec.get("stake_usd") if rec.get("stake_usd") is not None else "",
                result=result,
                pnl=pnl_s,
                why=why,
            )
        )
    lines.append("")
    return "\n".join(lines)


def _stats(closed: list[dict[str, Any]]) -> dict[str, float]:
    wins = [r for r in closed if r.get("won") is True]
    losses = [r for r in closed if r.get("won") is False]
    win_pnls = [_money(r.get("pnl")) for r in wins]
    loss_pnls = [_money(r.get("pnl")) for r in losses]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for rec in closed:
        equity += _money(rec.get("pnl"))
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    n = len(closed)
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
    return {
        "n": float(n),
        "win_rate": (len(wins) / n) if n else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "drawdown": max_dd,
        "rr": (avg_win / abs(avg_loss)) if avg_loss else 0.0,
    }


def _learnings(closed: list[dict[str, Any]]) -> str:
    lines = [
        "# Learnings",
        "",
        "Observations only. One trade does not change the live strategy.",
        "",
    ]
    if not closed:
        lines.append("No settled trades yet.")
        lines.append("")
        return "\n".join(lines)
    last = closed[-5:]
    loss_sides: dict[str, int] = {}
    for rec in closed:
        if rec.get("won") is False:
            side = str(rec.get("side") or "?")
            loss_sides[side] = loss_sides.get(side, 0) + 1
    if loss_sides:
        bits = ", ".join(f"{side} {n}" for side, n in sorted(loss_sides.items()))
        lines.append(f"- Settled losses by side: {bits}.")
    recent_losses = [r for r in last if r.get("won") is False]
    if len(recent_losses) >= 3:
        lines.append("- Three or more of the last five settled tickets lost. That is a pattern to review, not a reason to flip sides.")
    sold = [r for r in closed if str(r.get("result") or "") == "LIVE_SOLD"]
    if sold:
        lines.append(f"- {len(sold)} ticket(s) were sold because the other side was priced above 80%.")
    if len(lines) == 4:
        lines.append("- No repeated mistake stands out from the settled tickets yet.")
    lines.append("")
    return "\n".join(lines)


def _maybe_review(closed: list[dict[str, Any]]) -> None:
    n = len(closed)
    state_path = _dir() / "review_state.json"
    state = {"last_10": 0, "last_25": 0}
    if state_path.is_file():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state["last_10"] = int(raw.get("last_10") or 0)
                state["last_25"] = int(raw.get("last_25") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    block = n // 10
    block25 = n // 25
    if block <= state["last_10"] and block25 <= state["last_25"]:
        return
    stats = _stats(closed)
    chunks = []
    if block > state["last_10"] and block > 0:
        chunks.append(
            f"## After {block * 10} settled trades\n\n"
            f"Win rate {stats['win_rate']:.0%}. Average win ${stats['avg_win']:.2f}. "
            f"Average loss ${stats['avg_loss']:.2f}. Drawdown ${stats['drawdown']:.2f}. "
            "No rule change from this review.\n"
        )
        state["last_10"] = block
    if block25 > state["last_25"] and block25 > 0:
        chunks.append(
            f"## After {block25 * 25} settled trades\n\n"
            f"Win rate {stats['win_rate']:.0%}. Average win ${stats['avg_win']:.2f}. "
            f"Average loss ${stats['avg_loss']:.2f}. Reward/risk {stats['rr']:.2f}. "
            f"Drawdown ${stats['drawdown']:.2f}. "
            "Suggestions stay in this file. The live clip, the side picker, and the 76 cent cap stay as they are.\n"
        )
        state["last_25"] = block25
    if not chunks:
        return
    review = _dir() / "Trade_Review.md"
    prior = review.read_text(encoding="utf-8") if review.is_file() else "# Trade review\n\n"
    review.write_text(prior.rstrip() + "\n\n" + "\n".join(chunks), encoding="utf-8")
    state_path.write_text(json.dumps(state), encoding="utf-8")


def refresh_operating_notes() -> None:
    """Rewrite the context, ledger, and learnings. Append a review on the 10 and 25 marks."""
    rows = _settled(_load_fills())
    closed = [r for r in rows if r.get("won") is not None]
    _write("Trading_Context.md", _context())
    _write("Trade_Ledger.md", _ledger_md(rows))
    _write("Learnings.md", _learnings(closed))
    _maybe_review(closed)
