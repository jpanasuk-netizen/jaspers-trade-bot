"""Shared math and file locks for the ETH 15m study.

Research only. This module does not import the desk and does not place orders.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
CANDLES = CACHE / "candles.csv"
MANIFEST = ROOT / "manifest.json"
DESIGN_OUT = ROOT / "design_results.json"
CONFIRM_OUT = ROOT / "confirm_results.json"
SEALED_OUT = ROOT / "sealed_results.json"
RUN_LOG = ROOT / "RUN_LOG.md"

PAYOUT = 1.8
FEE = 0.0006
NET_WIN = PAYOUT - 1.0 - FEE
NET_LOSS = 1.0 + FEE
BREAKEVEN = (1.0 + FEE) / PAYOUT
WIN_MIN = 0.57
MIN_TRADES = 500
KELLY_HALF = 0.5
KELLY_CAP = 0.25
MIN_CAL_N = 800
MIN_BARS = 100_000
MAX_MISSING_FRAC = 0.01
BAR_MS = 900_000

HASHED_SOURCES = (
    "common.py",
    "strategies.py",
    "selftest.py",
    "fetch_split.py",
    "run_design.py",
    "run_confirm.py",
    "run_sealed.py",
)


def half_kelly(p: float) -> float:
    """Half of the Kelly fraction for decimal odds PAYOUT and a stake fee.

    Returns 0 when the edge is not positive. Does not apply KELLY_CAP.
    """
    if not math.isfinite(p) or p <= 0.0 or p >= 1.0:
        return 0.0
    b = NET_WIN / NET_LOSS
    full = (b * p - (1.0 - p)) / b
    if full <= 0.0:
        return 0.0
    return KELLY_HALF * full


def stake_fraction(p: float) -> tuple[float, bool]:
    raw = half_kelly(p)
    capped = raw > KELLY_CAP
    return (min(raw, KELLY_CAP), capped)


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    z2 = z * z
    den = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / den
    margin = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / den
    return (max(0.0, center - margin), min(1.0, center + margin))


def slice_bounds(n: int) -> dict[str, list[int] | int]:
    """Hide the last floor(n/3) bars. Split the visible prefix in half.

    Calendar rules fit on the first half of the design slice and the design
    gate for those rules uses only the second half of the design slice.
    """
    if n < 6:
        raise ValueError("need at least 6 bars to split")
    sealed_count = n // 3
    sealed_start = n - sealed_count
    design_end = sealed_start // 2
    fit_end = design_end // 2
    return {
        "n": n,
        "fit": [0, fit_end],
        "design": [0, design_end],
        "design_calendar": [fit_end, design_end],
        "confirm": [design_end, sealed_start],
        "sealed": [sealed_start, n],
    }


def score_predictions(
    pred: bytearray | list[int],
    labels: list[int],
    start: int,
    end: int,
    *,
    name: str,
    family: str,
    eligible: bool,
    kelly_p: float | None,
    kelly_in_sample: bool,
) -> dict[str, object]:
    wins = losses = pushes = 0
    outcomes = bytearray()
    for i in range(start, end):
        side = pred[i]
        if side == 0:
            continue
        y = labels[i]
        if y == 0:
            pushes += 1
            outcomes.append(2)
        elif side == y:
            wins += 1
            outcomes.append(1)
        else:
            losses += 1
            outcomes.append(0)
    decided = wins + losses
    wr = (wins / decided) if decided else 0.0
    low, high = wilson(wins, decided)
    if decided:
        flat_ev = (wins * NET_WIN - losses * NET_LOSS) / decided
    else:
        flat_ev = 0.0
    flat_pnl = wins * NET_WIN - losses * NET_LOSS - pushes * FEE
    if kelly_p is None:
        kelly_p = wr if decided else 0.0
    frac, capped = stake_fraction(float(kelly_p))
    bank = 1.0
    peak = 1.0
    max_dd = 0.0
    for y in outcomes:
        stake = frac * bank
        if y == 1:
            bank += stake * NET_WIN
        elif y == 0:
            bank -= stake * NET_LOSS
        else:
            bank -= stake * FEE
        if bank > peak:
            peak = bank
        if peak > 0.0:
            dd = (peak - bank) / peak
            if dd > max_dd:
                max_dd = dd
        if bank <= 0.0:
            bank = 0.0
            max_dd = 1.0
            break
    if bank > 0.0 and decided > 0 and frac > 0.0:
        log_growth = math.log(bank) / decided
    else:
        log_growth = 0.0
    if not eligible:
        passed = False
        reason = "control"
    elif decided < MIN_TRADES:
        passed = False
        reason = "too_few_trades"
    elif not (wr > WIN_MIN):
        passed = False
        reason = "win_rate"
    else:
        passed = True
        reason = None
    return {
        "name": name,
        "family": family,
        "eligible": eligible,
        "slice": [start, end],
        "trades": decided,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": wr,
        "wilson_low": low,
        "wilson_high": high,
        "clears_breakeven_95": bool(decided) and low > BREAKEVEN,
        "flat_ev_per_trade": flat_ev,
        "flat_pnl_sum": flat_pnl,
        "kelly_p": float(kelly_p),
        "kelly_in_sample": kelly_in_sample,
        "half_kelly_fraction": frac,
        "kelly_capped": capped,
        "terminal_bankroll": bank,
        "max_drawdown": max_dd,
        "log_growth_per_trade": log_growth,
        "pass": passed,
        "fail_reason": reason,
    }


def base_rate(labels: list[int], start: int, end: int) -> dict[str, object]:
    up = down = push = 0
    for i in range(start, end):
        y = labels[i]
        if y > 0:
            up += 1
        elif y < 0:
            down += 1
        else:
            push += 1
    decided = up + down
    return {
        "up": up,
        "down": down,
        "push": push,
        "up_rate": (up / decided) if decided else None,
        "rows": end - start,
    }


def source_hash() -> str:
    digest = hashlib.sha256()
    for name in HASHED_SOURCES:
        data = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def require_source_hash(manifest: dict[str, object]) -> None:
    current = source_hash()
    locked = str(manifest.get("source_hash") or "")
    if current != locked:
        raise SystemExit(
            "source hash changed after the split was locked; refusing to score"
        )


def load_candles() -> list[tuple[int, float, float, float, float, float]]:
    rows: list[tuple[int, float, float, float, float, float]] = []
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


def append_log(text: str) -> None:
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def stage_summary(results: list[dict[str, object]]) -> dict[str, object]:
    eligible = [row for row in results if row.get("eligible")]
    passed = [row for row in eligible if row.get("pass")]
    enough = [row for row in eligible if int(row["trades"]) >= MIN_TRADES]
    wrs = sorted(float(row["win_rate"]) for row in enough)

    def _quantile(p: float) -> float | None:
        if not wrs:
            return None
        index = min(len(wrs) - 1, max(0, int(round(p * (len(wrs) - 1)))))
        return wrs[index]

    families: dict[str, list[float]] = {}
    for row in enough:
        families.setdefault(str(row["family"]), []).append(float(row["win_rate"]))
    family_median = {
        name: sorted(values)[len(values) // 2]
        for name, values in sorted(families.items())
    }
    top = sorted(enough, key=lambda row: (-float(row["win_rate"]), str(row["name"])))[:12]
    return {
        "eligible": len(eligible),
        "with_min_trades": len(enough),
        "passed": len(passed),
        "median_win_rate": _quantile(0.5),
        "max_win_rate": wrs[-1] if wrs else None,
        "above_055": sum(1 for row in enough if float(row["win_rate"]) > 0.55),
        "above_057": sum(1 for row in enough if float(row["win_rate"]) > 0.57),
        "above_060": sum(1 for row in enough if float(row["win_rate"]) > 0.60),
        "family_median": family_median,
        "top": [
            {
                "name": row["name"],
                "family": row["family"],
                "trades": row["trades"],
                "win_rate": row["win_rate"],
                "flat_ev_per_trade": row["flat_ev_per_trade"],
                "terminal_bankroll": row["terminal_bankroll"],
                "max_drawdown": row["max_drawdown"],
            }
            for row in top
        ],
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def refuse_if(path: Path, message: str) -> None:
    if path.exists():
        raise SystemExit(message)
