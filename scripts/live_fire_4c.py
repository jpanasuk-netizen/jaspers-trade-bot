"""Live fire: 1 contract on KXBTC15M with ~4c budget (3c ticket + 1c fee)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.kalshi_live import (  # noqa: E402
    _kreq,
    ensure_shard_funds,
    load_creds,
    place_order,
)
from app.market import snapshot  # noqa: E402
from app.config import config  # noqa: E402
from app.btcc_knowledge import btcc_signal_board  # noqa: E402
from app.quantdinger import btc_research_pack  # noqa: E402

BUDGET = 0.04
SIDE = "YES"  # BTCC + QD fair-book edge both pointed YES on last read


def main() -> None:
    print("=== LIVE FIRE 4c ===")
    print("LIVE_MARK", config.live_mark, config.live_mark.is_file() if hasattr(config.live_mark, "is_file") else "")
    key_id, pk = load_creds()
    print("key_id loaded", bool(key_id), "pem", bool(pk))

    st, bal = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/balance")
    print("balance status", st)
    print(json.dumps(bal, indent=2)[:800])
    shards = {}
    for row in (bal.get("balance_breakdown") or []):
        try:
            shards[int(row.get("exchange_index", -1))] = float(row.get("balance") or 0)
        except (TypeError, ValueError):
            continue
    print("shards", shards)
    total = float(bal.get("balance") or sum(shards.values()) or 0)
    print("total_usd", total)

    snap = snapshot()
    win = snap.get("window") or {}
    act = (snap.get("kalshi") or {}).get("active") or win
    ticker = act.get("ticker") or win.get("ticker")
    print("ticker", ticker, "yes_ask", act.get("yes_ask"), "no_ask", act.get("no_ask"), "yes_mid", act.get("yes_mid"))
    print("spot", (snap.get("spot") or {}).get("price"), "open", act.get("open_of_window"), "secs", act.get("seconds_left"))
    print("fair", (snap.get("fast_feed") or {}).get("fair_yes"), "edge", (snap.get("fast_feed") or {}).get("edge_vs_book"))

    board = btcc_signal_board()
    qd = btc_research_pack()
    print("BTCC", board.get("lean"), board.get("setup"), board.get("confidence"), "hyg", board.get("hygiene"))
    print("QD", ((qd.get("btc") or {}).get("decision") or {}).get("lean"), ((qd.get("btc") or {}).get("models") or {}))

    side = SIDE
    b_lean = str(board.get("lean") or "").upper()
    q_lean = str(((qd.get("btc") or {}).get("decision") or {}).get("lean") or "").upper()
    if b_lean in {"YES", "NO"}:
        side = b_lean
    elif q_lean in {"YES", "NO"}:
        side = q_lean
    print("chosen side", side)

    # move funds to crypto shard 2 if needed
    try:
        shard = ensure_shard_funds(key_id, pk, dest_shard=int(config.kalshi_exchange_index or 2), min_dollars=0.05)
        print("shard_move", json.dumps(shard, indent=2)[:500])
    except Exception as exc:  # noqa: BLE001
        print("shard_move_error", exc)
        shard = {}

    if not ticker:
        print("NO_TICKER — cannot place")
        return
    if total < 0.01 and float(shard.get("dest_cash") or 0) < 0.01:
        print("NO_CASH — account balance too low for even a 1c contract")
        return

    print(f"PLACING live order side={side} stake~{BUDGET} ticker={ticker}")
    try:
        rec = place_order(ticker, side, act, stake_usd=BUDGET)
        print("ORDER_RESULT")
        print(json.dumps(rec, indent=2)[:2000])
        out = ROOT / "data" / "logs" / "live_fire_4c.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"ts": time.time(), "side": side, "ticker": ticker, "rec": rec}, indent=2), encoding="utf-8")
        print("saved", out)
    except Exception as exc:  # noqa: BLE001
        print("ORDER_FAILED", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
