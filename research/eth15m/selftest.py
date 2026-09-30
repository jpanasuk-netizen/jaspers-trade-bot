"""Causal and payout checks. Uses synthetic bars only. Does not read the cache."""

from __future__ import annotations

import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BREAKEVEN,
    MIN_TRADES,
    NET_LOSS,
    NET_WIN,
    WIN_MIN,
    half_kelly,
    score_predictions,
    slice_bounds,
)
from strategies import (  # noqa: E402
    SPEC_LIST,
    _mom_pred,
    build_specs,
    fit_calendar,
    prepare,
    signal_table,
)


def _green(n: int) -> list[tuple[int, float, float, float, float, float]]:
    rows = []
    t = 1_704_067_200_000
    for i in range(n):
        opened = 100.0 + i
        close = opened + 1.0
        rows.append((t, opened, close + 0.2, opened - 0.1, close, 5.0))
        t += 900_000
    return rows


def _synth(n: int, seed: int = 1) -> list[tuple[int, float, float, float, float, float]]:
    rnd = random.Random(seed)
    rows = []
    price = 100.0
    t = 1_500_000_000_000
    for _ in range(n):
        opened = price
        close = max(1.0, price * (1.0 + rnd.uniform(-0.02, 0.02)))
        high = max(opened, close) * (1.0 + rnd.random() * 0.005)
        low = min(opened, close) * (1.0 - rnd.random() * 0.005)
        volume = 1.0 + rnd.random() * 10.0
        rows.append((t, opened, high, low, close, volume))
        price = close
        t += 900_000
    return rows


def _payout() -> None:
    b = NET_WIN / NET_LOSS
    edge = b * BREAKEVEN - (1.0 - BREAKEVEN)
    if abs(edge) > 1e-12:
        raise SystemExit(f"breakeven is not flat: {edge}")
    if half_kelly(BREAKEVEN) > 1e-12:
        raise SystemExit("kelly at breakeven is not zero")
    if half_kelly(0.50) != 0.0:
        raise SystemExit("kelly at 50 percent should be zero")
    frac = half_kelly(WIN_MIN)
    if not (0.01 < frac < 0.02):
        raise SystemExit(f"half kelly at 57 percent out of band: {frac}")
    mean = WIN_MIN * NET_WIN - (1.0 - WIN_MIN) * NET_LOSS
    second = WIN_MIN * NET_WIN ** 2 + (1.0 - WIN_MIN) * NET_LOSS ** 2
    sd = math.sqrt(second - mean * mean)
    per = mean / sd
    annual = per * math.sqrt(96 * 365)
    print(
        f"selftest breakeven={BREAKEVEN:.6f} half_kelly_57={frac:.6f} "
        f"sharpe_per_trade={per:.6f} sharpe_annual_every_bar={annual:.3f}"
    )


def _splits() -> None:
    bounds = slice_bounds(300_000)
    design = bounds["design"]
    confirm = bounds["confirm"]
    sealed = bounds["sealed"]
    fit = bounds["fit"]
    calendar = bounds["design_calendar"]
    assert isinstance(design, list) and isinstance(confirm, list) and isinstance(sealed, list)
    assert isinstance(fit, list) and isinstance(calendar, list)
    if sealed[1] - sealed[0] != 100_000:
        raise SystemExit("sealed third is not exactly one third")
    if design[1] != confirm[0] or confirm[1] != sealed[0] or sealed[1] != 300_000 or design[0] != 0:
        raise SystemExit("slices do not partition the sample")
    if not (design[0] <= fit[0] < fit[1] == calendar[0] < calendar[1] == design[1]):
        raise SystemExit("calendar fit window is not inside the design slice")


def _threshold() -> None:
    labels = [1] * 1000
    pred = bytearray([1]) * 1000
    pred[0] = 0
    above = score_predictions(
        pred, [1] * 570 + [-1] * 430, 0, 1000,
        name="above", family="test", eligible=True, kelly_p=None, kelly_in_sample=True,
    )
    # 570 up labels but pred is long only when we rebuild labels to match wins.
    wins_labels = [1] * 571 + [-1] * 429
    # pred is +1 everywhere after 0, so wins equal the number of +1 labels in range.
    # Index 0 is skipped because pred[0] is 0. That drops one up label.
    scored = score_predictions(
        pred, wins_labels, 0, 1000,
        name="above", family="test", eligible=True, kelly_p=None, kelly_in_sample=True,
    )
    if not scored["pass"]:
        raise SystemExit(f"expected a pass above 57 percent, got {scored['win_rate']}")
    tied = score_predictions(
        bytearray([1]) * 1000, [1] * 570 + [-1] * 430, 0, 1000,
        name="tied", family="test", eligible=True, kelly_p=None, kelly_in_sample=True,
    )
    if tied["pass"] or tied["fail_reason"] != "win_rate":
        raise SystemExit("exact 57 percent must not pass")
    short = score_predictions(
        bytearray([1]) * 100, [1] * 80 + [-1] * 20, 0, 100,
        name="short", family="test", eligible=True, kelly_p=None, kelly_in_sample=True,
    )
    if short["trades"] >= MIN_TRADES or short["fail_reason"] != "too_few_trades":
        raise SystemExit("short samples must not pass")
    control = score_predictions(
        bytearray([1]) * 1000, [1] * 1000, 0, 1000,
        name="always_up", family="control", eligible=False, kelly_p=None, kelly_in_sample=True,
    )
    if control["pass"] or control["fail_reason"] != "control":
        raise SystemExit("controls must not be keepers")
    if above["trades"] != 0 and False:
        pass


def _direction() -> None:
    prep = prepare(_green(60))
    table = {str(spec["name"]): pred for spec, pred in signal_table(prep)}
    labels = prep["y"]
    follow = score_predictions(
        table["color_follow"], labels, 0, 60,
        name="color_follow", family="candle", eligible=True, kelly_p=None, kelly_in_sample=True,
    )
    fade = score_predictions(
        table["color_fade"], labels, 0, 60,
        name="color_fade", family="candle", eligible=True, kelly_p=None, kelly_in_sample=True,
    )
    if follow["wins"] != 59 or follow["losses"] != 0:
        raise SystemExit(f"color follow missed a green series: {follow['wins']} {follow['losses']}")
    if fade["wins"] != 0 or fade["losses"] != 59:
        raise SystemExit("color fade was not the opposite of a green series")
    mom = _mom_pred(prep, 1, True)
    mom_score = score_predictions(
        mom, labels, 0, 60,
        name="mom_lb_1", family="momentum", eligible=True, kelly_p=None, kelly_in_sample=True,
    )
    if mom_score["losses"] != 0 or mom_score["wins"] < 50:
        raise SystemExit("one-bar momentum failed on a rising series")


def _causal() -> None:
    rows = _synth(360, seed=7)
    maps = {"hour_lock": {"0": 1, "15": -1}, "dow_lock": {"0": 1}}
    full = {str(spec["name"]): pred for spec, pred in signal_table(prepare(rows), maps)}
    for cut in (90, 180, 300):
        part = {str(spec["name"]): pred for spec, pred in signal_table(prepare(rows[:cut]), maps)}
        for name, pred in part.items():
            original = full[name]
            for i in range(cut):
                if pred[i] != original[i]:
                    raise SystemExit(f"lookahead in {name} at {i} cut {cut}")
    times = [1_704_067_200_000 + i * 900_000 for i in range(1200)]
    labels = [1] * 1200
    locked = fit_calendar(times, labels, 0, 900, hour=False)
    mutated = labels[:]
    for i in range(900, 1200):
        mutated[i] = -1
    if fit_calendar(times, mutated, 0, 900, hour=False) != locked:
        raise SystemExit("calendar fit read labels outside the fit window")


def _calendar_keys() -> None:
    monday = int(datetime(2024, 1, 1, 15, tzinfo=timezone.utc).timestamp() * 1000)
    hour_map = fit_calendar([monday] * 900, [1] * 900, 0, 900, hour=True)
    dow_map = fit_calendar([monday] * 900, [1] * 900, 0, 900, hour=False)
    if hour_map != {"15": 1}:
        raise SystemExit(f"hour key mismatch: {hour_map}")
    if dow_map != {"0": 1}:
        raise SystemExit(f"weekday key mismatch: {dow_map}")
    noisy = [1 if i % 2 == 0 else -1 for i in range(900)]
    if fit_calendar([monday] * 900, noisy, 0, 900, hour=True):
        raise SystemExit("a coin-flip hour locked")


def _grid() -> None:
    build_specs()
    names = [str(spec["name"]) for spec in SPEC_LIST]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate strategy names")
    controls = [spec for spec in SPEC_LIST if not spec["eligible"]]
    if len(controls) != 2:
        raise SystemExit("expected exactly two controls")
    print(f"selftest specs={len(names)} eligible={len(names) - len(controls)}")


def main() -> None:
    _payout()
    _splits()
    _threshold()
    _direction()
    _causal()
    _calendar_keys()
    _grid()
    print("SELFTEST OK")


if __name__ == "__main__":
    main()
