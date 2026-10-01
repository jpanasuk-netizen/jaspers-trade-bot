"""ETH streak-fade signal. Same causal rule as the sealed study.

A signal at this window uses only candles that have already closed.
streak_fade_5 and streak_fade_6 are one bet: length 6 is the stricter size.
"""

from __future__ import annotations

# Half Kelly locked on the ETH design slice. Do not refit.
FADE_5_FRACTION = 0.036712393450017075
FADE_6_FRACTION = 0.03171117506240596
WIN_GATE = 0.57


def candle_color(open_px: float, close_px: float) -> int:
    if close_px > open_px:
        return 1
    if close_px < open_px:
        return -1
    return 0


def completed_streak(colors: list[int]) -> tuple[int, int]:
    """Run length and side after the last completed candle. A push resets."""
    run = 0
    prev = 0
    for side in colors:
        if side != 0 and side == prev:
            run += 1
        elif side != 0:
            prev = side
            run = 1
        else:
            prev = 0
            run = 0
    return run, prev


def fade_signal(colors: list[int]) -> dict[str, object] | None:
    """Fade a completed run of 5 or more. None when the rule is silent."""
    run, prev = completed_streak(colors)
    if run < 5 or prev == 0:
        return None
    bet = -prev
    length = 6 if run >= 6 else 5
    return {
        "run": run,
        "streak_color": prev,
        "rule": f"streak_fade_{length}",
        "side": "YES" if bet > 0 else "NO",
        "half_kelly": FADE_6_FRACTION if length == 6 else FADE_5_FRACTION,
    }


def breakeven_win_rate(pay: float, count: float, fee: float) -> float:
    """Win rate that zeros a contract costing pay plus fee and paying 1 if right."""
    if count <= 0:
        return 1.0
    return (count * pay + fee) / count


def price_ok(pay: float, count: float, fee: float) -> bool:
    return breakeven_win_rate(pay, count, fee) < WIN_GATE


def shared_budget(cash: float, fraction: float, reserve: float) -> float:
    """Half Kelly of the shared cash, after leaving the other desk's clip."""
    room = max(0.0, float(cash) - float(reserve))
    want = max(0.0, float(fraction) * float(cash))
    return round(min(want, room), 4)
