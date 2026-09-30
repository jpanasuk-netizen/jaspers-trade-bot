"""Score the frozen grid on Bitcoin. design, confirm, or sealed.

Sealed runs once and only scores confirm survivors. Prints aggregates only.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import sit  # noqa: F401

from common import (  # noqa: E402
    CANDLES,
    CONFIRM_OUT,
    DESIGN_OUT,
    SEALED_OUT,
    append_log,
    base_rate,
    file_sha256,
    load_manifest,
    refuse_if,
    require_source_hash,
    score_predictions,
    stage_summary,
    write_json,
)
from strategies import fit_calendar, prepare, signal_table  # noqa: E402


def _load_rows():
    rows = []
    with CANDLES.open("r", encoding="utf-8") as handle:
        header = handle.readline()
        if not header.startswith("open_time_ms"):
            raise SystemExit("candle cache is missing its header")
        for line in handle:
            parts = line.strip().split(",")
            if len(parts) != 6:
                continue
            rows.append(
                (
                    int(parts[0]),
                    float(parts[1]),
                    float(parts[2]),
                    float(parts[3]),
                    float(parts[4]),
                    float(parts[5]),
                )
            )
    return rows


def _check_lock(manifest) -> None:
    require_source_hash(manifest)
    if sit.driver_hash() != str(manifest.get("driver_hash") or ""):
        raise SystemExit("bitcoin driver hash changed after the split was locked")
    if file_sha256(CANDLES) != manifest["hashes"]["file"]:
        raise SystemExit("candle cache does not match the locked hash")


def _slice_hash(start: int, end: int) -> str:
    digest = hashlib.sha256()
    with CANDLES.open("r", encoding="utf-8") as handle:
        handle.readline()
        for idx, line in enumerate(handle):
            if idx < start:
                continue
            if idx >= end:
                break
            digest.update(line.encode())
    return digest.hexdigest()


def design() -> None:
    refuse_if(CONFIRM_OUT, "confirm results already exist; refusing to rescore design")
    manifest = load_manifest()
    _check_lock(manifest)
    rows = _load_rows()
    if len(rows) != manifest["n"]:
        raise SystemExit("candle count does not match the manifest")
    prep = prepare(rows)
    bounds = manifest["bounds"]
    fit_lo, fit_hi = bounds["fit"]
    design_lo, design_hi = bounds["design"]
    cal_lo, cal_hi = bounds["design_calendar"]
    labels = prep["y"]
    times = prep["ot"]
    maps = {
        "hour_lock": fit_calendar(times, labels, fit_lo, fit_hi, hour=True),
        "dow_lock": fit_calendar(times, labels, fit_lo, fit_hi, hour=False),
    }
    table = signal_table(prep, maps)
    names = [str(spec["name"]) for spec, _pred in table]
    if names != list(manifest["strategy_names"]):
        raise SystemExit("strategy grid does not match the locked manifest")
    results = []
    for spec, pred in table:
        if spec["kind"] == "calendar":
            start, end = cal_lo, cal_hi
        else:
            start, end = design_lo, design_hi
        results.append(
            score_predictions(
                pred,
                labels,
                start,
                end,
                name=str(spec["name"]),
                family=str(spec["family"]),
                eligible=bool(spec["eligible"]),
                kelly_p=None,
                kelly_in_sample=True,
            )
        )
    summary = stage_summary(results)
    payload = {
        "stage": "design",
        "symbol": "BTCUSDT",
        "source_hash": manifest["source_hash"],
        "candle_sha256": manifest["hashes"]["file"],
        "bounds": {
            "design": bounds["design"],
            "design_calendar": bounds["design_calendar"],
            "fit": bounds["fit"],
        },
        "base_rate": base_rate(labels, design_lo, design_hi),
        "calendar_fit_base_rate": base_rate(labels, fit_lo, fit_hi),
        "calendar_maps": maps,
        "summary": summary,
        "results": results,
    }
    write_json(DESIGN_OUT, payload)
    append_log(
        "\n## Design\n\n"
        f"- base up rate: {payload['base_rate']['up_rate']}\n"
        f"- eligible: {summary['eligible']}\n"
        f"- with minimum trades: {summary['with_min_trades']}\n"
        f"- passed: {summary['passed']}\n"
        f"- median win rate: {summary['median_win_rate']}\n"
        f"- max win rate: {summary['max_win_rate']}\n"
        f"- hour locks: {sorted(maps['hour_lock'])}\n"
        f"- weekday locks: {sorted(maps['dow_lock'])}\n"
    )
    print(
        f"DESIGN OK passed={summary['passed']} median={summary['median_win_rate']} "
        f"max={summary['max_win_rate']} base_up={payload['base_rate']['up_rate']}",
        flush=True,
    )


def confirm() -> None:
    refuse_if(SEALED_OUT, "sealed results already exist; refusing to rescore confirm")
    if not DESIGN_OUT.exists():
        raise SystemExit("design results are missing")
    manifest = load_manifest()
    _check_lock(manifest)
    design_doc = json.loads(DESIGN_OUT.read_text(encoding="utf-8"))
    passed = [row for row in design_doc["results"] if row["pass"]]
    rows = _load_rows()
    if len(rows) != manifest["n"]:
        raise SystemExit("candle count does not match the manifest")
    prep = prepare(rows)
    labels = prep["y"]
    start, end = manifest["bounds"]["confirm"]
    results = []
    if passed:
        wanted = {row["name"] for row in passed}
        table = signal_table(prep, design_doc["calendar_maps"], only=wanted)
        by_name = {str(spec["name"]): pred for spec, pred in table}
        if set(by_name) != wanted:
            raise SystemExit("confirm could not rebuild every design survivor")
        for row in passed:
            scored = score_predictions(
                by_name[row["name"]],
                labels,
                start,
                end,
                name=row["name"],
                family=row["family"],
                eligible=True,
                kelly_p=float(row["kelly_p"]),
                kelly_in_sample=False,
            )
            scored["design_win_rate"] = row["win_rate"]
            scored["design_trades"] = row["trades"]
            results.append(scored)
    summary = stage_summary(results)
    payload = {
        "stage": "confirm",
        "symbol": "BTCUSDT",
        "source_hash": manifest["source_hash"],
        "candle_sha256": manifest["hashes"]["file"],
        "bounds": {"confirm": [start, end]},
        "base_rate": base_rate(labels, start, end),
        "design_pass_count": len(passed),
        "summary": summary,
        "results": results,
    }
    write_json(CONFIRM_OUT, payload)
    append_log(
        "\n## Confirm\n\n"
        f"- design passers scored: {len(passed)}\n"
        f"- confirm base up rate: {payload['base_rate']['up_rate']}\n"
        f"- passed: {summary['passed']}\n"
        f"- median win rate: {summary['median_win_rate']}\n"
        f"- max win rate: {summary['max_win_rate']}\n"
    )
    print(
        f"CONFIRM OK scored={len(passed)} passed={summary['passed']} "
        f"max={summary['max_win_rate']} base_up={payload['base_rate']['up_rate']}",
        flush=True,
    )


def sealed() -> None:
    if SEALED_OUT.exists():
        raise SystemExit("sealed results already exist; refusing to look again")
    if not CONFIRM_OUT.exists() or not DESIGN_OUT.exists():
        raise SystemExit("confirm results are missing")
    manifest = load_manifest()
    _check_lock(manifest)
    start, end = manifest["bounds"]["sealed"]
    if _slice_hash(start, end) != manifest["hashes"]["sealed"]:
        raise SystemExit("sealed slice hash does not match the lock")
    confirm_doc = json.loads(CONFIRM_OUT.read_text(encoding="utf-8"))
    design_doc = json.loads(DESIGN_OUT.read_text(encoding="utf-8"))
    passed = [row for row in confirm_doc["results"] if row["pass"]]
    rows = _load_rows()
    if len(rows) != manifest["n"]:
        raise SystemExit("candle count does not match the manifest")
    prep = prepare(rows)
    labels = prep["y"]
    results = []
    if passed:
        wanted = {row["name"] for row in passed}
        table = signal_table(prep, design_doc["calendar_maps"], only=wanted)
        by_name = {str(spec["name"]): pred for spec, pred in table}
        if set(by_name) != wanted:
            raise SystemExit("sealed validation could not rebuild every confirm survivor")
        for row in passed:
            scored = score_predictions(
                by_name[row["name"]],
                labels,
                start,
                end,
                name=row["name"],
                family=row["family"],
                eligible=True,
                kelly_p=float(row["kelly_p"]),
                kelly_in_sample=False,
            )
            scored["design_win_rate"] = row.get("design_win_rate")
            scored["confirm_win_rate"] = row["win_rate"]
            scored["confirm_trades"] = row["trades"]
            results.append(scored)
    summary = stage_summary(results)
    payload = {
        "stage": "sealed",
        "symbol": "BTCUSDT",
        "source_hash": manifest["source_hash"],
        "candle_sha256": manifest["hashes"]["file"],
        "sealed_sha256": manifest["hashes"]["sealed"],
        "bounds": {"sealed": [start, end]},
        "base_rate": base_rate(labels, start, end),
        "confirm_pass_count": len(passed),
        "summary": summary,
        "results": results,
        "kept": [row["name"] for row in results if row["pass"]],
    }
    blob = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd = os.open(SEALED_OUT, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)
    append_log(
        "\n## Sealed\n\n"
        f"- confirm passers scored: {len(passed)}\n"
        f"- sealed base up rate: {payload['base_rate']['up_rate']}\n"
        f"- kept: {payload['kept']}\n"
        f"- passed: {summary['passed']}\n"
        f"- max win rate: {summary['max_win_rate']}\n"
    )
    print(
        f"SEALED OK scored={len(passed)} kept={len(payload['kept'])} "
        f"max={summary['max_win_rate']} base_up={payload['base_rate']['up_rate']}",
        flush=True,
    )


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "design":
        design()
    elif cmd == "confirm":
        confirm()
    elif cmd == "sealed":
        sealed()
    else:
        raise SystemExit("usage: stage.py design|confirm|sealed")


if __name__ == "__main__":
    main()
