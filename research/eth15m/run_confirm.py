"""Score design survivors on the confirm slice. Does not refit anything."""

from __future__ import annotations

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
    refuse_if,
    require_source_hash,
    score_predictions,
    stage_summary,
    write_json,
)
from strategies import prepare, signal_table  # noqa: E402


def main() -> None:
    refuse_if(SEALED_OUT, "sealed results already exist; refusing to rescore confirm")
    if not DESIGN_OUT.exists():
        raise SystemExit("design results are missing")
    manifest = load_manifest()
    require_source_hash(manifest)
    if file_sha256(CANDLES) != manifest["hashes"]["file"]:
        raise SystemExit("candle cache does not match the locked hash")
    design = __import__("json").loads(DESIGN_OUT.read_text(encoding="utf-8"))
    passed = [row for row in design["results"] if row["pass"]]
    rows = load_candles()
    if len(rows) != manifest["n"]:
        raise SystemExit("candle count does not match the manifest")
    prep = prepare(rows)
    labels = prep["y"]
    assert isinstance(labels, list)
    start, end = manifest["bounds"]["confirm"]
    results = []
    if passed:
        wanted = {row["name"] for row in passed}
        table = signal_table(prep, design["calendar_maps"], only=wanted)
        found = {str(spec["name"]) for spec, _pred in table}
        if found != wanted:
            raise SystemExit("confirm could not rebuild every design survivor")
        by_name = {str(spec["name"]): pred for spec, pred in table}
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
        f"max={summary['max_win_rate']} base_up={payload['base_rate']['up_rate']}"
    )


if __name__ == "__main__":
    main()
