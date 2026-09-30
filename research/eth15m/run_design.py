"""Score the pre-registered grid on the design slice only."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CONFIRM_OUT,
    DESIGN_OUT,
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
from strategies import fit_calendar, prepare, signal_table  # noqa: E402


def main() -> None:
    refuse_if(CONFIRM_OUT, "confirm results already exist; refusing to rescore design")
    manifest = load_manifest()
    require_source_hash(manifest)
    if file_sha256(Path(__file__).resolve().parent / "cache" / "candles.csv") != manifest["hashes"]["file"]:
        raise SystemExit("candle cache does not match the locked hash")
    rows = load_candles()
    if len(rows) != manifest["n"]:
        raise SystemExit("candle count does not match the manifest")
    prep = prepare(rows)
    bounds = manifest["bounds"]
    fit_lo, fit_hi = bounds["fit"]
    design_lo, design_hi = bounds["design"]
    cal_lo, cal_hi = bounds["design_calendar"]
    labels = prep["y"]
    times = prep["ot"]
    assert isinstance(labels, list) and isinstance(times, list)
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
        "source_hash": manifest["source_hash"],
        "candle_sha256": manifest["hashes"]["file"],
        "bounds": {"design": bounds["design"], "design_calendar": bounds["design_calendar"], "fit": bounds["fit"]},
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
        f"max={summary['max_win_rate']} base_up={payload['base_rate']['up_rate']}"
    )


if __name__ == "__main__":
    main()
