"""One-shot validation of confirm survivors on the sealed third.

Refuses to run twice. Does not score the rest of the grid. Prints aggregates only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CANDLES,
    CONFIRM_OUT,
    DESIGN_OUT,
    SEALED_OUT,
    append_log,
    base_rate,
    file_sha256,
    load_candles,
    load_manifest,
    require_source_hash,
    score_predictions,
    stage_summary,
)

def _slice_hash(start: int, end: int) -> str:
    import hashlib

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


def main() -> None:
    if SEALED_OUT.exists():
        raise SystemExit("sealed results already exist; refusing to look again")
    if not CONFIRM_OUT.exists() or not DESIGN_OUT.exists():
        raise SystemExit("confirm results are missing")
    manifest = load_manifest()
    require_source_hash(manifest)
    if file_sha256(CANDLES) != manifest["hashes"]["file"]:
        raise SystemExit("candle cache does not match the locked hash")
    start, end = manifest["bounds"]["sealed"]
    if _slice_hash(start, end) != manifest["hashes"]["sealed"]:
        raise SystemExit("sealed slice hash does not match the lock")
    confirm = json.loads(CONFIRM_OUT.read_text(encoding="utf-8"))
    design = json.loads(DESIGN_OUT.read_text(encoding="utf-8"))
    passed = [row for row in confirm["results"] if row["pass"]]
    rows = load_candles()
    if len(rows) != manifest["n"]:
        raise SystemExit("candle count does not match the manifest")
    from strategies import prepare, signal_table

    prep = prepare(rows)
    labels = prep["y"]
    assert isinstance(labels, list)
    results = []
    if passed:
        wanted = {row["name"] for row in passed}
        table = signal_table(prep, design["calendar_maps"], only=wanted)
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
    fd = os.open(SEALED_OUT, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
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
        f"max={summary['max_win_rate']} base_up={payload['base_rate']['up_rate']}"
    )


if __name__ == "__main__":
    main()
