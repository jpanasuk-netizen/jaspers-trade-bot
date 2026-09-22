"""A skipped window is one ledger line, written when the next window starts."""
import json
import tempfile
from pathlib import Path

import app.spin as spin


def main() -> None:
    root = Path(tempfile.mkdtemp())
    paths = {
        "ledger": root / "spin_ledger.jsonl",
        "spun": root / "spun.json",
        "scoreboard": root / "scoreboard.json",
        "day_pnl": root / "day_pnl.json",
        "blocks": root / "blocks.json",
    }
    spin._paths = lambda: paths

    first = {"ticker": "WIN-A", "result": "RISK_GATE_BLOCK", "reason": "volatility"}
    spin._remember_skip(dict(first))
    spin._remember_skip(dict(first, reason="volatility again"))
    assert not paths["ledger"].exists() or paths["ledger"].read_text(encoding="utf-8").strip() == ""

    spin._remember_skip({"ticker": "WIN-B", "result": "SKIP_ENTRY", "reason": "context disagrees"})
    lines = [json.loads(line) for line in paths["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert lines[0]["ticker"] == "WIN-A"
    assert lines[0]["window_skip"] is True
    assert lines[0]["reason"] == "volatility again"

    spin._remember_skip({"ticker": "WIN-B", "result": "SKIP_ENTRY", "reason": "still no"})
    lines = [json.loads(line) for line in paths["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, lines

    spin.mark_spun("WIN-B")
    spin._remember_skip({"ticker": "WIN-C", "result": "SKIP", "reason": "next"})
    lines = [json.loads(line) for line in paths["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["ticker"] for row in lines] == ["WIN-A"], lines
    closed = {"ticker": "WIN-D", "result": "SKIP_ENTRY", "reason": "closed", "seconds_left": 0}
    spin._remember_skip(dict(closed))
    lines = [json.loads(line) for line in paths["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["ticker"] for row in lines] == ["WIN-A", "WIN-C", "WIN-D"], lines

    from app.kalshi_live import sized_quote

    clip = sized_quote("YES", {"yes_ask": 0.50, "no_ask": 0.51}, 2.0)
    assert clip is not None and clip["count"] > 1.0, clip
    one = sized_quote("YES", {"yes_ask": 0.50, "no_ask": 0.51}, 9.0, max_count=1.0)
    assert one is not None and one["count"] == 1.0, one
    cut = spin.salvage_reason(
        "YES",
        0.62,
        0.28,
        100.0,
        110.0,
        {},
        {"yes_bid": 0.28, "yes_ask": 0.30, "no_ask": 0.72},
        100,
    )
    assert cut and "tape flipped" in cut, cut
    hold = spin.salvage_reason(
        "YES",
        0.55,
        0.52,
        110.0,
        100.0,
        {},
        {"yes_bid": 0.52, "yes_ask": 0.55, "no_ask": 0.48},
        100,
    )
    assert hold is None, hold
    dust = spin.salvage_reason(
        "YES", 0.62, 0.02, 100.0, 110.0, {}, {"yes_bid": 0.02, "yes_ask": 0.04}, 100
    )
    assert dust is None, dust
    assert spin.fill_pnl({"stake_usd": 2.0, "quote": {"count": 3}}, True) == 1.0
    assert spin.fill_pnl({"stake_usd": 2.0, "quote": {"count": 3}}, False) == -2.0
    print("window skip ok")


if __name__ == "__main__":
    main()
