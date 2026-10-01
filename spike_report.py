#!/usr/bin/env python3
"""Compare Jev vs fade/follow shadows on data/spike.jsonl (dry-run report)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import sys

sys.path.insert(0, "/home/jpanasuk/jev-15m-kalshi-bot")
from app.config import config  # noqa: E402

path = Path(config.data_dir) / "spike.jsonl"
if not path.is_file():
    print("no spike log yet:", path)
    raise SystemExit(0)

rows = [json.loads(line) for line in path.read_text(errors="replace").splitlines() if line.strip()]
spikes = [r for r in rows if r.get("type") == "spike"]
trades = [r for r in rows if r.get("type") == "trade"]
print(f"{len(spikes)} spikes · {len(trades)} closed trades")

def line(name, ts):
    if not ts:
        print(f"  {name:16} no closed trades")
        return
    win = sum(1 for t in ts if float(t.get("pnl_contract") or 0) > 0)
    total = sum(float(t.get("pnl_contract") or 0) for t in ts)
    by = defaultdict(int)
    for t in ts:
        by[t.get("reason")] += 1
    avg_hold = sum(float(t.get("held_min") or 0) for t in ts) / len(ts)
    print(
        f"  {name:16} {len(ts):3d} trades · win {100*win/len(ts):3.0f}% · "
        f"total {total:+.3f} contract · exits {dict(by)} · avg hold {avg_hold:.1f} min"
    )

print("closed trades:")
for who in ("jev", "fade", "follow"):
    line(who, [t for t in trades if t.get("who") == who])
