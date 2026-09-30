"""Pre-registered ETH 15-minute up/down rules.

A prediction at index i uses only bars strictly before i. Positive predicts
an up candle (close > open). Negative predicts down. Zero skips.

Calendar maps are fit outside this grid, on the design prefix only, and passed
back in. This module does not read the sealed slice and does not place orders.
"""

from __future__ import annotations

import array
import math
from collections import deque

from common import MIN_CAL_N, WIN_MIN

SPEC_LIST: list[dict[str, object]] = []


def _add(name: str, family: str, kind: str, fn: object, eligible: bool = True) -> None:
    SPEC_LIST.append(
        {
            "name": name,
            "family": family,
            "kind": kind,
            "fn": fn,
            "eligible": eligible,
        }
    )


def _zeros(n: int) -> array.array:
    return array.array("b", bytes(n))


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period or period < 1:
        return out
    k = 2.0 / (period + 1.0)
    acc = sum(values[:period]) / period
    out[period - 1] = acc
    for i in range(period, len(values)):
        acc = values[i] * k + acc * (1.0 - k)
        out[i] = acc
    return out


def _ema_optional(values: list[float | None], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    buf: list[float] = []
    started = False
    acc = 0.0
    k = 2.0 / (period + 1.0)
    for i, value in enumerate(values):
        if value is None:
            continue
        if not started:
            buf.append(value)
            if len(buf) == period:
                acc = sum(buf) / period
                out[i] = acc
                started = True
            continue
        acc = value * k + acc * (1.0 - k)
        out[i] = acc
    return out


def _rsi(closes: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gain = 0.0
    loss = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gain += max(delta, 0.0)
        loss += max(-delta, 0.0)
    avg_g = gain / period
    avg_l = loss / period

    def _value(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = _value(avg_g, avg_l)
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(delta, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-delta, 0.0)) / period
        out[i] = _value(avg_g, avg_l)
    return out


def _roll_mean_std(values: list[float], period: int) -> tuple[list[float | None], list[float | None]]:
    n = len(values)
    means: list[float | None] = [None] * n
    stds: list[float | None] = [None] * n
    if n < period or period < 2:
        return means, stds
    total = sum(values[:period])
    squares = sum(x * x for x in values[:period])

    def _emit(i: int, tot: float, sq: float) -> None:
        mean = tot / period
        var = sq / period - mean * mean
        if var < 0.0:
            var = 0.0
        means[i] = mean
        stds[i] = math.sqrt(var)

    _emit(period - 1, total, squares)
    for i in range(period, n):
        old = values[i - period]
        new = values[i]
        total += new - old
        squares += new * new - old * old
        _emit(i, total, squares)
    return means, stds


def _rolling_extreme(values: list[float], window: int, want_max: bool) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if window < 1:
        return out
    dq: deque[int] = deque()
    for i, value in enumerate(values):
        if want_max:
            while dq and values[dq[-1]] <= value:
                dq.pop()
        else:
            while dq and values[dq[-1]] >= value:
                dq.pop()
        dq.append(i)
        while dq and dq[0] <= i - window:
            dq.popleft()
        if i >= window - 1:
            out[i] = values[dq[0]]
    return out


def _atr(high: list[float], low: list[float], close: list[float], period: int) -> list[float | None]:
    n = len(close)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    tr: list[float] = [0.0] * n
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    acc = sum(tr[1 : period + 1]) / period
    out[period] = acc
    for i in range(period + 1, n):
        acc = (acc * (period - 1) + tr[i]) / period
        out[i] = acc
    return out


def _prefix(values: list[float]) -> list[float]:
    out = [0.0]
    total = 0.0
    for value in values:
        total += value
        out.append(total)
    return out


def precompute(prep: dict[str, object]) -> dict[str, object]:
    close = prep["c"]
    high = prep["h"]
    low = prep["l"]
    assert isinstance(close, list) and isinstance(high, list) and isinstance(low, list)
    cache: dict[str, object] = {}
    for period in (3, 5, 8, 12, 13, 20, 21, 26, 50, 55, 100, 200):
        cache[f"ema_{period}"] = _ema(close, period)
    for period in (7, 14, 21):
        cache[f"rsi_{period}"] = _rsi(close, period)
    for period in (20, 48):
        means, stds = _roll_mean_std(close, period)
        cache[f"bb_mean_{period}"] = means
        cache[f"bb_std_{period}"] = stds
    for window in (5, 8, 10, 14, 16, 20, 32, 48, 96):
        cache[f"max_h_{window}"] = _rolling_extreme(high, window, True)
        cache[f"min_l_{window}"] = _rolling_extreme(low, window, False)
    cache["atr_14"] = _atr(high, low, close, 14)
    typical = [(high[i] + low[i] + close[i]) / 3.0 for i in range(len(close))]
    cache["tp"] = typical
    cache["tpv_prefix"] = _prefix([typical[i] * prep["v"][i] for i in range(len(close))])  # type: ignore[index]
    cache["v_prefix"] = _prefix(prep["v"])  # type: ignore[arg-type]
    returns = [0.0] * len(close)
    for i in range(1, len(close)):
        prev = close[i - 1]
        returns[i] = (close[i] / prev - 1.0) if prev else 0.0
    cache["ret"] = returns
    cache["ret_prefix"] = _prefix(returns)
    cache["ret2_prefix"] = _prefix([r * r for r in returns])
    macd: list[float | None] = [None] * len(close)
    ema_fast = cache["ema_12"]
    ema_slow = cache["ema_26"]
    assert isinstance(ema_fast, list) and isinstance(ema_slow, list)
    for i in range(len(close)):
        fast = ema_fast[i]
        slow = ema_slow[i]
        if fast is not None and slow is not None:
            macd[i] = fast - slow
    cache["macd"] = macd
    cache["macd_signal"] = _ema_optional(macd, 9)
    return cache


def _color_pred(prep: dict[str, object], follow: bool) -> bytearray:
    opened = prep["o"]
    close = prep["c"]
    assert isinstance(opened, list) and isinstance(close, list)
    pred = _zeros(len(close))
    for i in range(1, len(close)):
        if close[i - 1] > opened[i - 1]:
            pred[i] = 1 if follow else -1
        elif close[i - 1] < opened[i - 1]:
            pred[i] = -1 if follow else 1
    return pred


def _mom_pred(prep: dict[str, object], lookback: int, follow: bool) -> bytearray:
    close = prep["c"]
    assert isinstance(close, list)
    pred = _zeros(len(close))
    for i in range(lookback + 1, len(close)):
        delta = close[i - 1] - close[i - 1 - lookback]
        if delta > 0.0:
            pred[i] = 1 if follow else -1
        elif delta < 0.0:
            pred[i] = -1 if follow else 1
    return pred


def _streak_pred(prep: dict[str, object], length: int, follow: bool) -> bytearray:
    opened = prep["o"]
    close = prep["c"]
    assert isinstance(opened, list) and isinstance(close, list)
    n = len(close)
    color = [0] * n
    for i in range(n):
        if close[i] > opened[i]:
            color[i] = 1
        elif close[i] < opened[i]:
            color[i] = -1
    pred = _zeros(n)
    run = 0
    prev = 0
    for i in range(n):
        if i >= length and run >= length and prev != 0:
            pred[i] = prev if follow else -prev
        side = color[i]
        if side != 0 and side == prev:
            run += 1
        elif side != 0:
            prev = side
            run = 1
        else:
            prev = 0
            run = 0
    return pred


def _rsi_pred(cache: dict[str, object], period: int, hi: float | None, lo: float | None, follow: bool) -> bytearray:
    series = cache[f"rsi_{period}"]
    assert isinstance(series, list)
    pred = _zeros(len(series))
    for i in range(1, len(series)):
        value = series[i - 1]
        if value is None:
            continue
        if follow:
            if value > 50.0:
                pred[i] = 1
            elif value < 50.0:
                pred[i] = -1
            continue
        assert hi is not None and lo is not None
        if value >= hi:
            pred[i] = -1
        elif value <= lo:
            pred[i] = 1
    return pred


def _ema_cross_pred(cache: dict[str, object], fast: int, slow: int) -> bytearray:
    a = cache[f"ema_{fast}"]
    b = cache[f"ema_{slow}"]
    assert isinstance(a, list) and isinstance(b, list)
    pred = _zeros(len(a))
    for i in range(1, len(a)):
        left = a[i - 1]
        right = b[i - 1]
        if left is None or right is None:
            continue
        if left > right:
            pred[i] = 1
        elif left < right:
            pred[i] = -1
    return pred


def _ema_side_pred(prep: dict[str, object], cache: dict[str, object], period: int) -> bytearray:
    close = prep["c"]
    series = cache[f"ema_{period}"]
    assert isinstance(close, list) and isinstance(series, list)
    pred = _zeros(len(close))
    for i in range(1, len(close)):
        basis = series[i - 1]
        if basis is None:
            continue
        if close[i - 1] > basis:
            pred[i] = 1
        elif close[i - 1] < basis:
            pred[i] = -1
    return pred


def _bb_pred(prep: dict[str, object], cache: dict[str, object], period: int, width: float, fade: bool) -> bytearray:
    close = prep["c"]
    means = cache[f"bb_mean_{period}"]
    stds = cache[f"bb_std_{period}"]
    assert isinstance(close, list) and isinstance(means, list) and isinstance(stds, list)
    pred = _zeros(len(close))
    for i in range(1, len(close)):
        mid = means[i - 1]
        sd = stds[i - 1]
        if mid is None or sd is None or sd == 0.0:
            continue
        upper = mid + width * sd
        lower = mid - width * sd
        price = close[i - 1]
        if price > upper:
            pred[i] = -1 if fade else 1
        elif price < lower:
            pred[i] = 1 if fade else -1
    return pred


def _z_pred(cache: dict[str, object], lookback: int, threshold: float, fade: bool) -> bytearray:
    returns = cache["ret"]
    prefix = cache["ret_prefix"]
    square_prefix = cache["ret2_prefix"]
    assert isinstance(returns, list) and isinstance(prefix, list) and isinstance(square_prefix, list)
    n = len(returns)
    pred = _zeros(n)
    for i in range(lookback + 2, n):
        last = i - 1
        begin = last - lookback
        if begin < 1:
            continue
        total = prefix[last] - prefix[begin]
        squares = square_prefix[last] - square_prefix[begin]
        mean = total / lookback
        var = squares / lookback - mean * mean
        if var <= 0.0:
            continue
        z = (returns[last] - mean) / math.sqrt(var)
        if z >= threshold:
            pred[i] = -1 if fade else 1
        elif z <= -threshold:
            pred[i] = 1 if fade else -1
    return pred


def _vol_pred(prep: dict[str, object], cache: dict[str, object], lookback: int, mult: float, follow: bool) -> bytearray:
    volume = prep["v"]
    opened = prep["o"]
    close = prep["c"]
    prefix = cache["v_prefix"]
    assert isinstance(volume, list) and isinstance(opened, list) and isinstance(close, list) and isinstance(prefix, list)
    pred = _zeros(len(close))
    for i in range(lookback + 1, len(close)):
        end = i - 1
        begin = end - lookback
        baseline = (prefix[end] - prefix[begin]) / lookback
        if baseline <= 0.0 or volume[end] <= mult * baseline:
            continue
        if close[end] > opened[end]:
            pred[i] = 1 if follow else -1
        elif close[end] < opened[end]:
            pred[i] = -1 if follow else 1
    return pred


def _donchian_pred(prep: dict[str, object], cache: dict[str, object], window: int, fade: bool) -> bytearray:
    close = prep["c"]
    highs = cache[f"max_h_{window}"]
    lows = cache[f"min_l_{window}"]
    assert isinstance(close, list) and isinstance(highs, list) and isinstance(lows, list)
    pred = _zeros(len(close))
    for i in range(window + 2, len(close)):
        prior_high = highs[i - 2]
        prior_low = lows[i - 2]
        if prior_high is None or prior_low is None:
            continue
        price = close[i - 1]
        if price > prior_high:
            pred[i] = -1 if fade else 1
        elif price < prior_low:
            pred[i] = 1 if fade else -1
    return pred


def _macd_pred(cache: dict[str, object]) -> bytearray:
    macd = cache["macd"]
    signal = cache["macd_signal"]
    assert isinstance(macd, list) and isinstance(signal, list)
    pred = _zeros(len(macd))
    for i in range(1, len(macd)):
        line = macd[i - 1]
        basis = signal[i - 1]
        if line is None or basis is None:
            continue
        hist = line - basis
        if hist > 0.0:
            pred[i] = 1
        elif hist < 0.0:
            pred[i] = -1
    return pred


def _stoch_pred(prep: dict[str, object], cache: dict[str, object], window: int, hi: float, lo: float, follow: bool) -> bytearray:
    close = prep["c"]
    highs = cache[f"max_h_{window}"]
    lows = cache[f"min_l_{window}"]
    assert isinstance(close, list) and isinstance(highs, list) and isinstance(lows, list)
    pred = _zeros(len(close))
    for i in range(1, len(close)):
        top = highs[i - 1]
        bot = lows[i - 1]
        if top is None or bot is None or top == bot:
            continue
        k = (close[i - 1] - bot) / (top - bot) * 100.0
        if follow:
            if k >= hi:
                pred[i] = 1
            elif k <= lo:
                pred[i] = -1
        else:
            if k >= hi:
                pred[i] = -1
            elif k <= lo:
                pred[i] = 1
    return pred


def _range_pred(prep: dict[str, object], cache: dict[str, object], window: int, threshold: float, fade: bool) -> bytearray:
    close = prep["c"]
    highs = cache[f"max_h_{window}"]
    lows = cache[f"min_l_{window}"]
    assert isinstance(close, list) and isinstance(highs, list) and isinstance(lows, list)
    pred = _zeros(len(close))
    for i in range(1, len(close)):
        top = highs[i - 1]
        bot = lows[i - 1]
        if top is None or bot is None or top == bot:
            continue
        pos = (close[i - 1] - bot) / (top - bot)
        if pos >= threshold:
            pred[i] = -1 if fade else 1
        elif pos <= 1.0 - threshold:
            pred[i] = 1 if fade else -1
    return pred


def _body_pred(prep: dict[str, object], threshold: float, follow: bool) -> bytearray:
    opened = prep["o"]
    high = prep["h"]
    low = prep["l"]
    close = prep["c"]
    assert isinstance(opened, list) and isinstance(high, list) and isinstance(low, list) and isinstance(close, list)
    pred = _zeros(len(close))
    for i in range(1, len(close)):
        span = high[i - 1] - low[i - 1]
        if span <= 0.0:
            continue
        ratio = abs(close[i - 1] - opened[i - 1]) / span
        if ratio < threshold:
            continue
        if close[i - 1] > opened[i - 1]:
            pred[i] = 1 if follow else -1
        elif close[i - 1] < opened[i - 1]:
            pred[i] = -1 if follow else 1
    return pred


def _vwap_pred(prep: dict[str, object], cache: dict[str, object], lookback: int, atr_mult: float, fade: bool) -> bytearray:
    close = prep["c"]
    tpv = cache["tpv_prefix"]
    vol = cache["v_prefix"]
    atr = cache["atr_14"]
    assert isinstance(close, list) and isinstance(tpv, list) and isinstance(vol, list) and isinstance(atr, list)
    pred = _zeros(len(close))
    for i in range(lookback + 1, len(close)):
        end = i - 1
        begin = end - lookback + 1
        if begin < 0:
            continue
        volume = vol[end + 1] - vol[begin]
        if volume <= 0.0:
            continue
        vwap = (tpv[end + 1] - tpv[begin]) / volume
        scale = atr[end]
        if scale is None or scale <= 0.0:
            continue
        dist = (close[end] - vwap) / scale
        if dist >= atr_mult:
            pred[i] = -1 if fade else 1
        elif dist <= -atr_mult:
            pred[i] = 1 if fade else -1
    return pred


def _atr_mom_pred(prep: dict[str, object], cache: dict[str, object], rank: int, high_vol: bool) -> bytearray:
    opened = prep["o"]
    close = prep["c"]
    atr = cache["atr_14"]
    assert isinstance(opened, list) and isinstance(close, list) and isinstance(atr, list)
    pred = _zeros(len(close))
    window: deque[float] = deque()
    for i in range(len(close)):
        value = atr[i]
        if i >= 1 and len(window) == rank:
            cur = window[-1]
            if cur is not None:
                count = sum(1 for item in window if item <= cur)
                pct = count / rank
                take = pct >= 0.70 if high_vol else pct <= 0.30
                if take:
                    if close[i - 1] > opened[i - 1]:
                        pred[i] = 1
                    elif close[i - 1] < opened[i - 1]:
                        pred[i] = -1
        if value is not None:
            window.append(value)
            while len(window) > rank:
                window.popleft()
    return pred


def _always(n: int, side: int) -> bytearray:
    pred = _zeros(n)
    for i in range(1, n):
        pred[i] = side
    return pred


def _calendar_pred(prep: dict[str, object], locked: dict[str, int], hour: bool) -> bytearray:
    times = prep["ot"]
    assert isinstance(times, list)
    pred = _zeros(len(times))
    for i, ts in enumerate(times):
        if hour:
            key = str((int(ts) // 3_600_000) % 24)
        else:
            # Monday = 0. 1970-01-01 was a Thursday.
            days = int(ts) // 86_400_000
            key = str((days + 3) % 7)
        side = locked.get(key, 0)
        if side == 1 or side == -1:
            pred[i] = side
    return pred


def fit_calendar(
    times: list[int],
    labels: list[int],
    start: int,
    end: int,
    hour: bool,
) -> dict[str, int]:
    buckets: dict[str, list[int]] = {}
    for i in range(start, end):
        y = labels[i]
        if y == 0:
            continue
        if hour:
            key = str((times[i] // 3_600_000) % 24)
        else:
            days = times[i] // 86_400_000
            key = str((days + 3) % 7)
        cell = buckets.setdefault(key, [0, 0])
        if y > 0:
            cell[0] += 1
        else:
            cell[1] += 1
    locked: dict[str, int] = {}
    for key, (up, down) in buckets.items():
        decided = up + down
        if decided < MIN_CAL_N:
            continue
        up_rate = up / decided
        down_rate = down / decided
        if up_rate > WIN_MIN:
            locked[key] = 1
        elif down_rate > WIN_MIN:
            locked[key] = -1
    return locked


def prepare(rows: list[tuple[int, float, float, float, float, float]]) -> dict[str, object]:
    labels: list[int] = []
    times: list[int] = []
    opened: list[float] = []
    high: list[float] = []
    low: list[float] = []
    close: list[float] = []
    volume: list[float] = []
    for ot, o, h, l, c, v in rows:
        times.append(ot)
        opened.append(o)
        high.append(h)
        low.append(l)
        close.append(c)
        volume.append(v)
        if c > o:
            labels.append(1)
        elif c < o:
            labels.append(-1)
        else:
            labels.append(0)
    return {"ot": times, "o": opened, "h": high, "l": low, "c": close, "v": volume, "y": labels}


def build_specs() -> None:
    if SPEC_LIST:
        return
    _add("color_follow", "candle", "std", lambda prep, cache, maps: _color_pred(prep, True))
    _add("color_fade", "candle", "std", lambda prep, cache, maps: _color_pred(prep, False))
    for lookback in (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96):
        _add(
            f"mom_lb_{lookback}",
            "momentum",
            "std",
            lambda prep, cache, maps, k=lookback: _mom_pred(prep, k, True),
        )
        _add(
            f"rev_lb_{lookback}",
            "reversal",
            "std",
            lambda prep, cache, maps, k=lookback: _mom_pred(prep, k, False),
        )
    for length in (2, 3, 4, 5, 6, 7, 8):
        _add(
            f"streak_fade_{length}",
            "streak",
            "std",
            lambda prep, cache, maps, n=length: _streak_pred(prep, n, False),
        )
    for length in (2, 3, 4, 5, 6):
        _add(
            f"streak_follow_{length}",
            "streak",
            "std",
            lambda prep, cache, maps, n=length: _streak_pred(prep, n, True),
        )
    for period in (7, 14, 21):
        for hi, lo in ((60.0, 40.0), (65.0, 35.0), (70.0, 30.0), (75.0, 25.0), (80.0, 20.0)):
            _add(
                f"rsi_fade_{period}_{int(hi)}_{int(lo)}",
                "rsi",
                "std",
                lambda prep, cache, maps, p=period, h=hi, l=lo: _rsi_pred(cache, p, h, l, False),
            )
        _add(
            f"rsi_follow_{period}",
            "rsi",
            "std",
            lambda prep, cache, maps, p=period: _rsi_pred(cache, p, None, None, True),
        )
    for fast, slow in ((3, 8), (5, 13), (8, 21), (12, 26), (20, 50), (21, 55)):
        _add(
            f"ema_cross_{fast}_{slow}",
            "trend",
            "std",
            lambda prep, cache, maps, a=fast, b=slow: _ema_cross_pred(cache, a, b),
        )
    for period in (8, 20, 50, 100, 200):
        _add(
            f"ema_side_{period}",
            "trend",
            "std",
            lambda prep, cache, maps, p=period: _ema_side_pred(prep, cache, p),
        )
    for period, width in ((20, 1.5), (20, 2.0), (20, 2.5), (48, 2.0)):
        tag = str(width).replace(".", "p")
        _add(
            f"bb_fade_{period}_{tag}",
            "band",
            "std",
            lambda prep, cache, maps, p=period, w=width: _bb_pred(prep, cache, p, w, True),
        )
        _add(
            f"bb_break_{period}_{tag}",
            "band",
            "std",
            lambda prep, cache, maps, p=period, w=width: _bb_pred(prep, cache, p, w, False),
        )
    for lookback in (20, 48, 96):
        for threshold in (1.0, 1.5, 2.0, 2.5):
            tag = str(threshold).replace(".", "p")
            _add(
                f"z_fade_{lookback}_{tag}",
                "zscore",
                "std",
                lambda prep, cache, maps, k=lookback, t=threshold: _z_pred(cache, k, t, True),
            )
            _add(
                f"z_follow_{lookback}_{tag}",
                "zscore",
                "std",
                lambda prep, cache, maps, k=lookback, t=threshold: _z_pred(cache, k, t, False),
            )
    for mult in (1.5, 2.0, 3.0):
        tag = str(mult).replace(".", "p")
        _add(
            f"vol_follow_20_{tag}",
            "volume",
            "std",
            lambda prep, cache, maps, m=mult: _vol_pred(prep, cache, 20, m, True),
        )
        _add(
            f"vol_fade_20_{tag}",
            "volume",
            "std",
            lambda prep, cache, maps, m=mult: _vol_pred(prep, cache, 20, m, False),
        )
    for window in (10, 20, 48, 96):
        _add(
            f"donchian_break_{window}",
            "channel",
            "std",
            lambda prep, cache, maps, w=window: _donchian_pred(prep, cache, w, False),
        )
        _add(
            f"donchian_fade_{window}",
            "channel",
            "std",
            lambda prep, cache, maps, w=window: _donchian_pred(prep, cache, w, True),
        )
    _add("macd_12_26_9", "trend", "std", lambda prep, cache, maps: _macd_pred(cache))
    for window, hi, lo in ((14, 80.0, 20.0), (14, 70.0, 30.0), (5, 80.0, 20.0)):
        _add(
            f"stoch_fade_{window}_{int(hi)}_{int(lo)}",
            "stoch",
            "std",
            lambda prep, cache, maps, w=window, h=hi, l=lo: _stoch_pred(prep, cache, w, h, l, False),
        )
        _add(
            f"stoch_follow_{window}_{int(hi)}_{int(lo)}",
            "stoch",
            "std",
            lambda prep, cache, maps, w=window, h=hi, l=lo: _stoch_pred(prep, cache, w, h, l, True),
        )
    for window in (8, 16, 32, 96):
        _add(
            f"range_break_{window}_0p8",
            "range",
            "std",
            lambda prep, cache, maps, w=window: _range_pred(prep, cache, w, 0.8, False),
        )
        _add(
            f"range_fade_{window}_0p8",
            "range",
            "std",
            lambda prep, cache, maps, w=window: _range_pred(prep, cache, w, 0.8, True),
        )
    for threshold in (0.5, 0.7):
        tag = str(threshold).replace(".", "p")
        _add(
            f"body_follow_{tag}",
            "candle",
            "std",
            lambda prep, cache, maps, t=threshold: _body_pred(prep, t, True),
        )
    for threshold in (0.7, 0.85):
        tag = str(threshold).replace(".", "p")
        _add(
            f"body_fade_{tag}",
            "candle",
            "std",
            lambda prep, cache, maps, t=threshold: _body_pred(prep, t, False),
        )
    for lookback in (16, 48, 96):
        for mult in (1.0, 2.0):
            tag = str(mult).replace(".", "p")
            _add(
                f"vwap_fade_{lookback}_{tag}",
                "vwap",
                "std",
                lambda prep, cache, maps, k=lookback, m=mult: _vwap_pred(prep, cache, k, m, True),
            )
            _add(
                f"vwap_follow_{lookback}_{tag}",
                "vwap",
                "std",
                lambda prep, cache, maps, k=lookback, m=mult: _vwap_pred(prep, cache, k, m, False),
            )
    _add(
        "atr_mom_high_14_96",
        "regime",
        "std",
        lambda prep, cache, maps: _atr_mom_pred(prep, cache, 96, True),
    )
    _add(
        "atr_mom_low_14_96",
        "regime",
        "std",
        lambda prep, cache, maps: _atr_mom_pred(prep, cache, 96, False),
    )
    _add(
        "hour_lock",
        "calendar",
        "calendar",
        lambda prep, cache, maps: _calendar_pred(prep, maps.get("hour_lock", {}), True),
    )
    _add(
        "dow_lock",
        "calendar",
        "calendar",
        lambda prep, cache, maps: _calendar_pred(prep, maps.get("dow_lock", {}), False),
    )
    _add(
        "always_up",
        "control",
        "control",
        lambda prep, cache, maps: _always(len(prep["c"]), 1),
        eligible=False,
    )
    _add(
        "always_down",
        "control",
        "control",
        lambda prep, cache, maps: _always(len(prep["c"]), -1),
        eligible=False,
    )


def signal_table(
    prep: dict[str, object],
    calendar_maps: dict[str, dict[str, int]] | None = None,
    only: set[str] | None = None,
) -> list[tuple[dict[str, object], array.array]]:
    build_specs()
    maps = calendar_maps or {"hour_lock": {}, "dow_lock": {}}
    cache = precompute(prep)
    table: list[tuple[dict[str, object], array.array]] = []
    for spec in SPEC_LIST:
        name = str(spec["name"])
        if only is not None and name not in only:
            continue
        fn = spec["fn"]
        assert callable(fn)
        pred = fn(prep, cache, maps)
        table.append((spec, pred))
    return table
