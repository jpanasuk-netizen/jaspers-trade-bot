"""Calibration tracker — Trackmind: skill vs noise / calibrated confidence.

After each settled fill, record (conf_band, won). When we claim 70% we should
hit ~70% of the time. Drift raises the conf floor automatically (sample-aware).
"""
from pathlib import Path
import json
import time

ROOT = Path("/mnt/c/Users/jpana/XiaomiMiMoProjects/2026-09-27/please-move-all-the-money-from")
CAL = Path("/home/jpanasuk/jev-15m-kalshi-bot/data/calibration.json")

def _load():
    if CAL.is_file():
        try:
            return json.loads(CAL.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"bands": {}, "n": 0, "hits": 0}

def record_settle(conf: float, won: bool) -> None:
    d = _load()
    band = round(float(conf), 1)  # 0.5, 0.6, 0.7 ...
    b = d["bands"].setdefault(str(band), {"n": 0, "wins": 0})
    b["n"] += 1
    b["wins"] += 1 if won else 0
    d["n"] += 1
    d["hits"] += 1 if won else 0
    d["updated"] = time.time()
    CAL.write_text(json.dumps(d, indent=2), encoding="utf-8")

def calibration_report() -> dict:
    d = _load()
    out = {"n": d.get("n", 0), "hit_rate": None, "bands": {}}
    if d.get("n"):
        out["hit_rate"] = round(d["hits"] / d["n"], 3)
    for band, b in (d.get("bands") or {}).items():
        if b.get("n"):
            out["bands"][band] = {
                "n": b["n"],
                "win_rate": round(b["wins"] / b["n"], 3),
                "gap": round(float(band) - (b["wins"] / b["n"]), 3),
            }
    return out

def suggest_conf_floor(default: float = 0.45, min_n: int = 12) -> float:
    """If high-conf band is underperforming, raise the floor. Trackmind: never
    trust a small sample — only move when n is real."""
    rep = calibration_report()
    bands = rep.get("bands") or {}
    # worst gap among bands with enough samples
    worst = 0.0
    for band, b in bands.items():
        if b["n"] >= min_n and b["gap"] > 0.12:
            worst = max(worst, b["gap"])
    if worst > 0:
        return round(min(0.85, default + worst * 0.5), 2)
    return default

if __name__ == "__main__":
    print(json.dumps(calibration_report(), indent=2))
    print("suggested conf_floor", suggest_conf_floor())
