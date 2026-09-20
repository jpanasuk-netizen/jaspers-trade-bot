"""Quant layer — measure randomness instead of feeling it.

Implements the Trackmind quant checklist inside the desk:
  1. Distribution shape (returns mean/vol/kurtosis proxies)
  2. Skill vs noise (Sharpe, min sample, hit-rate SE)
  3. Calibrated uncertainty (Brier / reliability on logged judgments)
  4. Pattern skepticism (out-of-sample flag, cost-aware edge)
  5. Tail attention (VaR proxy, fat-tail score)
  6. Fractional Kelly sizing (capped) — only when calibration holds
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from .config import config

MIN_SAMPLE_FOR_EDGE = int(__import__("os").environ.get("MIN_SAMPLE_FOR_EDGE", 30))
KELLY_FRACTION = float(__import__("os").environ.get("KELLY_FRACTION", 0.25))
KELLY_MAX_MULT = float(__import__("os").environ.get("KELLY_MAX_MULT", 2.0))
VAR_CONF = float(__import__("os").environ.get("VAR_CONF", 0.95))
BRIER_PASS = float(__import__("os").environ.get("BRIER_PASS", 0.25))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _kurtosis(xs: list[float]) -> float:
    """Excess kurtosis (0 = normal-ish). Higher = fatter tails."""
    n = len(xs)
    if n < 4:
        return 0.0
    m = _mean(xs)
    s = _std(xs)
    if s <= 1e-12:
        return 0.0
    z4 = sum(((x - m) / s) ** 4 for x in xs) / n
    return z4 - 3.0


def period_sharpe(returns: list[float]) -> float | None:
    """Per-period Sharpe (mean/std). Needs min sample — luck is not edge."""
    if len(returns) < MIN_SAMPLE_FOR_EDGE:
        return None
    sd = _std(returns)
    if sd <= 1e-12:
        return None
    return _mean(returns) / sd


def hit_rate_se(hits: int, n: int) -> float:
    """Standard error of hit rate — luck band."""
    if n <= 0:
        return 1.0
    p = hits / n
    return math.sqrt(max(p * (1 - p), 1e-12) / n)


def brier_score(pairs: list[tuple[float, int]]) -> float | None:
    """Mean (p - outcome)^2. Lower is better. None if empty."""
    if not pairs:
        return None
    return sum((p - float(y)) ** 2 for p, y in pairs) / len(pairs)


def calibration_report(pairs: list[tuple[float, int]], bins: int = 5) -> dict[str, Any]:
    """Reliability: predicted p vs empirical frequency."""
    if len(pairs) < MIN_SAMPLE_FOR_EDGE:
        return {
            "ok": False,
            "n": len(pairs),
            "brier": brier_score(pairs),
            "bins": [],
            "note": f"need >= {MIN_SAMPLE_FOR_EDGE} judgments for calibration",
        }
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for p, y in pairs:
        idx = min(bins - 1, max(0, int(p * bins)))
        buckets[idx].append((p, y))
    rows = []
    max_gap = 0.0
    for i, b in enumerate(buckets):
        if not b:
            continue
        pred = _mean([p for p, _ in b])
        emp = _mean([float(y) for _, y in b])
        gap = abs(pred - emp)
        max_gap = max(max_gap, gap)
        rows.append(
            {
                "bucket": f"{i / bins:.1f}-{(i + 1) / bins:.1f}",
                "n": len(b),
                "predicted": round(pred, 3),
                "empirical": round(emp, 3),
                "gap": round(gap, 3),
            }
        )
    br = brier_score(pairs)
    return {
        "ok": True,
        "n": len(pairs),
        "brier": br,
        "brier_pass": (br is not None and br <= BRIER_PASS),
        "max_calibration_gap": round(max_gap, 3),
        "bins": rows,
        "kelly_allowed": bool(br is not None and br <= BRIER_PASS and len(pairs) >= MIN_SAMPLE_FOR_EDGE),
    }


def historical_var(returns: list[float], conf: float = VAR_CONF) -> float | None:
    """Simple historical VaR (loss quantile). More negative = worse tail."""
    if len(returns) < MIN_SAMPLE_FOR_EDGE:
        return None
    s = sorted(returns)
    idx = int((1.0 - conf) * (len(s) - 1))
    idx = max(0, min(len(s) - 1, idx))
    return s[idx]


def tail_score(returns: list[float]) -> dict[str, Any]:
    k = _kurtosis(returns)
    var = historical_var(returns)
    return {
        "excess_kurtosis": round(k, 3),
        "var": round(var, 4) if var is not None else None,
        "fat_tail": k > 1.0,
        "note": "fat tails: size down; gut underweights edges",
    }


def fractional_kelly(
    p_win: float,
    win_net: float,
    lose_net: float,
    *,
    bankroll: float | None = None,
    calibrated: bool = False,
) -> dict[str, Any]:
    """Kelly f* = (b*p - q) / b, applied at KELLY_FRACTION and capped.

    Only allowed when calibration holds — uncalibrated 'confidence' is noise.
    """
    p = _clamp(p_win, 0.01, 0.99)
    q = 1.0 - p
    b = win_net / lose_net if lose_net > 0 else 0.0
    if b <= 0:
        return {"allowed": False, "reason": "non-positive odds", "kelly_full": 0.0, "kelly_frac": 0.0}
    kelly_full = (b * p - q) / b
    if kelly_full <= 0:
        return {
            "allowed": calibrated,
            "reason": "no positive edge under these odds",
            "kelly_full": round(kelly_full, 4),
            "kelly_frac": 0.0,
        }
    kelly_frac = kelly_full * KELLY_FRACTION
    if not calibrated:
        return {
            "allowed": False,
            "reason": "calibration not verified — Kelly forbidden",
            "kelly_full": round(kelly_full, 4),
            "kelly_frac": 0.0,
        }
    return {
        "allowed": True,
        "reason": "ok",
        "kelly_full": round(kelly_full, 4),
        "kelly_frac": round(kelly_frac, 4),
        "fraction": KELLY_FRACTION,
        "bankroll": bankroll,
    }


def outcome_good_decision_win(outcome_win: bool, followed_policy: bool) -> str:
    """Do not confuse a good outcome with a good decision."""
    if followed_policy and outcome_win:
        return "good_decision_good_outcome"
    if followed_policy and not outcome_win:
        return "good_decision_bad_outcome"  # still a good decision
    if not followed_policy and outcome_win:
        return "bad_decision_good_outcome"  # luck
    return "bad_decision_bad_outcome"


def load_ledger_returns(path: Path, limit: int = 200) -> list[float]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    rets: list[float] = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if rec.get("mode") not in {"PAPER", "LIVE"}:
            continue
        pnl = rec.get("pnl_usd")
        if pnl is None:
            result = str(rec.get("result") or "")
            stake = float(rec.get("stake_usd") or 0.0)
            if result in {"FILL_WIN", "WIN"}:
                pnl = stake * 0.8
            elif result in {"FILL_LOSS", "LOSS"}:
                pnl = -stake
            else:
                continue
        rets.append(float(pnl))
    return rets


def load_judgment_pairs(path: Path, limit: int = 300) -> list[tuple[float, int]]:
    """(predicted p_side, outcome 1/0) for calibration."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    pairs: list[tuple[float, int]] = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        j = rec.get("judge") or {}
        side = str(rec.get("side") or j.get("side") or "").upper()
        conf = float(rec.get("conf") or j.get("conf") or 0.0)
        settled = rec.get("settled_side") or rec.get("outcome_side")
        if side not in {"YES", "NO"} or not settled:
            continue
        y = 1 if str(settled).upper() == side else 0
        pairs.append((conf, y))
    return pairs


def live_pairs_from_charts() -> list[tuple[float, int]]:
    """Calibration pairs from live fair_YES vs current above-open label.

    Each chart tick with fair_yes + price/open is one observation:
      predicted = fair_yes (P(settle above open))
      outcome   = 1 if spot currently above open else 0
    This is valid in-window calibration of the fair model — not final settlement,
    but it fills immediately and moves with the desk.
    """
    try:
        from .chart_data import chart_series

        ch = chart_series()
    except Exception:  # noqa: BLE001
        return []
    pairs: list[tuple[float, int]] = []
    for p in ch.get("models") or []:
        fair = p.get("fair_yes")
        above = p.get("above_open")
        if fair is None or above is None:
            continue
        try:
            pairs.append((float(fair), int(above)))
        except (TypeError, ValueError):
            continue
    return pairs[-400:]


def live_returns_proxy() -> list[float]:
    """Notional paper returns: if fair>=0.5 we 'take YES' at book mid; PnL proxy.

    win  = (1 - yes_mid) when above_open, lose = -yes_mid when below.
    Used for Sharpe/tails until real fills exist.
    """
    try:
        from .chart_data import chart_series

        ch = chart_series()
    except Exception:  # noqa: BLE001
        return []
    rets: list[float] = []
    for p in ch.get("models") or []:
        fair = p.get("fair_yes")
        book = p.get("book_yes")
        above = p.get("above_open")
        if fair is None or book is None or above is None:
            continue
        try:
            f = float(fair)
            entry = float(book)
        except (TypeError, ValueError):
            continue
        if entry <= 0:
            continue
        side = 1 if f >= 0.5 else 0  # 1 = YES, 0 = NO
        if side == 1:
            rets.append((1.0 - entry) if int(above) == 1 else (-entry))
        else:
            rets.append(entry if int(above) == 0 else (-(1.0 - entry)))
    return rets[-200:]


def desk_quant_snapshot() -> dict[str, Any]:
    """Full quant report for HUD / risk — live charts + ledger + journal."""
    paths = config.data_dir
    rets_ledger = load_ledger_returns(paths / "spin_ledger.jsonl")
    pairs_ledger = load_judgment_pairs(paths / "spin_ledger.jsonl")
    pairs_live = live_pairs_from_charts()
    rets_live = live_returns_proxy()
    pairs = pairs_ledger + pairs_live
    rets = rets_ledger + rets_live
    hits = sum(1 for _, y in pairs if y == 1)
    n = len(pairs)
    n_live = len(pairs_live)
    n_ledger = len(pairs_ledger)
    cal = calibration_report(pairs) if n else {"ok": False, "n": 0, "brier": None, "bins": []}
    tails = tail_score(rets) if len(rets) >= 4 else {
        "excess_kurtosis": round(_kurtosis(rets), 3) if rets else 0.0,
        "var": None,
        "fat_tail": False,
    }
    if rets and len(rets) < MIN_SAMPLE_FOR_EDGE:
        tails["excess_kurtosis"] = round(_kurtosis(rets), 3) if len(rets) >= 4 else 0.0
    ps = period_sharpe(rets)
    # always expose a live activity number even when "too thin" for edge claims
    mean_edge = None
    try:
        from .chart_data import chart_series

        edges = [float(p["edge"]) for p in (chart_series().get("models") or []) if p.get("edge") is not None]
        if edges:
            mean_edge = round(sum(edges) / len(edges), 4)
    except Exception:  # noqa: BLE001
        mean_edge = None
    return {
        "sample_n_trades": len(rets),
        "sample_n_judgments": n,
        "sample_n_live": n_live,
        "sample_n_ledger": n_ledger,
        "hit_rate": round(hits / n, 3) if n else None,
        "hit_rate_se": round(hit_rate_se(hits, n), 4) if n else None,
        "hit_rate_luck_band": round(2 * hit_rate_se(hits, n), 4) if n else None,
        "period_sharpe": round(ps, 3) if ps is not None else None,
        "period_sharpe_note": (
            f"n={len(rets)}/{MIN_SAMPLE_FOR_EDGE} — wait for sample" if ps is None and rets else None
        ),
        "mean_pnl": round(_mean(rets), 4) if rets else None,
        "std_pnl": round(_std(rets), 4) if rets else None,
        "mean_fair_edge": mean_edge,
        "min_sample": MIN_SAMPLE_FOR_EDGE,
        "edge_statistically_visible": bool(n >= MIN_SAMPLE_FOR_EDGE and ps is not None and ps > 0),
        "calibration": cal,
        "tails": tails,
        "source": "live_fair_vs_open + ledger",
        "kelly_policy": {
            "fraction": KELLY_FRACTION,
            "allowed": bool(cal.get("kelly_allowed")),
            "note": "Kelly only after calibration passes; otherwise flat/fixed stake",
        },
        "principles": [
            "randomness has a shape — measure it",
            "skill vs noise needs sample size + Sharpe",
            "confidence must be calibrated to act",
            "patterns are fake until OOS + costs say otherwise",
            "tails do the damage — watch VaR/kurtosis",
            "good outcome ≠ good decision",
        ],
        "generated_at": time.time(),
    }


def apply_quant_to_stake(
    base_stake: float,
    judgment: dict[str, Any],
    *,
    bankroll: float | None = None,
) -> dict[str, Any]:
    """Policy engine: size from calibrated confidence, else fixed/min stake."""
    snap = desk_quant_snapshot()
    cal_ok = bool((snap.get("calibration") or {}).get("kelly_allowed"))
    probs = judgment.get("probabilities") or {}
    side = str(judgment.get("side") or "").upper()
    p = float(probs.get("yes") if side == "YES" else probs.get("no") if side == "NO" else 0.5) or 0.5
    # Kalshi binary approx: win net ≈ (1-entry)/entry, lose net ≈ 1
    entry = 0.5
    try:
        if side == "YES" and judgment.get("yes_mid") is not None:
            entry = float(judgment["yes_mid"])
        elif side == "NO" and judgment.get("yes_mid") is not None:
            entry = 1.0 - float(judgment["yes_mid"])
    except (TypeError, ValueError):
        entry = 0.5
    entry = _clamp(entry, 0.05, 0.95)
    win_net = (1.0 - entry) / entry
    lose_net = 1.0
    kelly = fractional_kelly(p, win_net, lose_net, bankroll=bankroll, calibrated=cal_ok)

    if snap.get("tails", {}).get("fat_tail") and float(snap.get("tails", {}).get("excess_kurtosis") or 0) > 2.5:
        base_stake = base_stake * 0.5  # tail-aware size-down

    if kelly.get("allowed") and float(kelly.get("kelly_frac") or 0) > 0:
        bank = bankroll if bankroll is not None else config.max_stake_usd
        sized = _clamp(bank * float(kelly["kelly_frac"]), 0.05, config.max_stake_usd * KELLY_MAX_MULT)
        # never exceed configured hard exposure cap
        sized = min(sized, config.max_stake_usd)
        return {
            "stake": round(sized, 4),
            "mode": "fractional_kelly" if cal_ok else "fixed",
            "kelly": kelly,
            "quant": {
                "calibration_ok": cal_ok,
                "brier": (snap.get("calibration") or {}).get("brier"),
                "hit_rate": snap.get("hit_rate"),
                "n": snap.get("sample_n_judgments"),
                "period_sharpe": snap.get("period_sharpe"),
                "fat_tail": snap.get("tails", {}).get("fat_tail"),
            },
        }
    return {
        "stake": round(base_stake, 4),
        "mode": "fixed_or_min",
        "kelly": kelly,
        "quant": {
            "calibration_ok": cal_ok,
            "brier": (snap.get("calibration") or {}).get("brier"),
            "hit_rate": snap.get("hit_rate"),
            "n": snap.get("sample_n_judgments"),
            "period_sharpe": snap.get("period_sharpe"),
            "fat_tail": snap.get("tails", {}).get("fat_tail"),
        },
        "note": kelly.get("reason") or "uncalibrated — do not size on raw confidence",
    }
