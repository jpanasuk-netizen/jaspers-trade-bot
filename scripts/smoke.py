#!/usr/bin/env python3
"""Smoke test: market snapshot, sentiment stats, judge, paper spin."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.market import snapshot  # noqa: E402
from app.sentiment import get_sentiment, process_tweets  # noqa: E402
from app.judge import deterministic_judge, judge  # noqa: E402
from app.spin import evaluate_spin, paper_fill, jev_to_side  # noqa: E402


def main() -> int:
    print("== market snapshot ==")
    mkt = snapshot()
    print(json.dumps({
        "spot_ok": mkt["spot"].get("ok"),
        "spot": mkt["spot"].get("price"),
        "kalshi_ok": mkt["kalshi"].get("ok"),
        "kalshi_count": mkt["kalshi"].get("count"),
        "ticker": mkt["window"].get("ticker"),
        "open": mkt["window"].get("open_of_window"),
        "yes_ask": mkt["window"].get("yes_ask"),
        "no_ask": mkt["window"].get("no_ask"),
        "seconds_left": mkt["window"].get("seconds_left"),
        "kalshi_err": mkt["kalshi"].get("error"),
    }, indent=2))

    print("\n== sentiment stats (unit) ==")
    stats = process_tweets([
        {"id": "1", "author_username": "a", "text": "btc pump moon buy", "likes": 10, "retweets": 2},
        {"id": "2", "author_username": "b", "text": "btc crash dump panic", "likes": 20, "retweets": 5},
        {"id": "3", "author_username": "c", "text": "btc breakout bull rally", "likes": 5, "retweets": 1},
    ])
    print(json.dumps({k: stats[k] for k in ("sample_size", "polarity_score", "sentiment_label")}, indent=2))

    print("\n== live sentiment snapshot ==")
    sent = get_sentiment("BTC", force=True)
    print(json.dumps({
        "is_mock": sent.get("is_mock"),
        "polarity": (sent.get("stats") or {}).get("polarity_score"),
        "label": (sent.get("stats") or {}).get("sentiment_label"),
        "sample": (sent.get("stats") or {}).get("sample_size"),
    }, indent=2))

    print("\n== deterministic judge ==")
    j = deterministic_judge(mkt, sent)
    print(json.dumps({
        "side": j["side"],
        "conf": j["conf"],
        "probs": j["probabilities"],
        "trade_action": j["trade_action"],
        "reason": j["reason"],
    }, indent=2))

    print("\n== cached judge() ==")
    j2 = judge(force=True)
    print(json.dumps({
        "src": j2.get("judge_src"),
        "side": j2.get("side"),
        "conf": j2.get("conf"),
        "ticker": (j2.get("window") or {}).get("ticker"),
    }, indent=2))

    print("\n== side map + paper fill ==")
    print("jev_to_side:", jev_to_side(j2))
    entry = j2.get("yes_mid") or 0.55
    print("paper_fill:", paper_fill("YES", float(entry), 2.0))

    print("\n== evaluate_spin (paper, may skip if already spun) ==")
    rec = evaluate_spin(force_judge=True)
    # don't dump huge judgment
    slim = {k: rec.get(k) for k in (
        "mode", "ticker", "result", "side", "conf", "entry",
        "spin_reason", "reason", "filled",
    )}
    print(json.dumps(slim, indent=2))
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
