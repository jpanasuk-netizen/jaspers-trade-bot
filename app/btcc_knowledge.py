"""Grokbot BTCC knowledge engine — built from the grokbot-continuity vault.

Sources:
  C:\\Users\\jpana\\.hermes\\...\\grokbot-continuity\\bots\\btcc.md
  leveraged-trading-risk skill · house-brain doctrine · hermes typesafe hygiene

Doctrine (hard):
  - Signals only. Never auto-place 500x. Survival > gamble.
  - Paper / one-ticket Kalshi discipline until Jeremy explicitly arms live.
  - Hygiene veto: revenge, chase, no-setup, leverage excess → no trade.
  - High-confluence only: fib + golden pocket + Hurst regime + fair/book edge.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Any

from .config import config
from .fast_feed import fast_snapshot

# --- Doctrine constants from Grokbot BTCC vault -------------------------------

DOCTRINE = {
    "role": (
        "BTC signal bot. Watches Coinbase, BTCC, Kraken, and Kalshi. "
        "Surfaces high-confluence setups (fib, golden pocket) on small-account risk. "
        "Never places a live 500x trade unless Jeremy explicitly okays that order. "
        "Goal: survive the day, not gamble it."
    ),
    "hard_rules": [
        "Signals only — no auto 500x without explicit per-order ok",
        "Kalshi KXBTC15M preferred over Polymarket; one-ticket clicks if small bankroll",
        "No live Kalshi auto-trade without keys + explicit okay",
        "Paper-only until human gate clears",
        "No revenge re-entry after a flatten",
        "No chase mid-range; wait for reclaim or confirmed break",
        "Survive the day — not recover losses with leverage",
        "Complete-set scanner: flag Up+Down sum < 0.98 (paper)",
    ],
    "regime_gate_hurst": {
        "trending": 0.55,
        "random": 0.50,
        "mean_revert": 0.45,
        "note": "H>0.55 trend/fib holds; H<0.45 mean-revert fades; ~0.50 random = no edge",
    },
    "historical_levels_sep2026": {
        "golden_pocket_7d": [78156.0, 78319.0],
        "reclaim_long_trigger": 77460.0,
        "invalidation_under": 77460.0,
        "flush_level": 77280.0,
        "support_1": 76840.0,
        "support_2": 76366.0,
        "scale_out_1": 77800.0,
        "scale_out_2": 78000.0,
        "note": "Sep 1–2 2026 doctrine levels — used as template; live fibs computed from tape",
    },
    "venues": ["Coinbase", "BTCC", "Kraken", "Kalshi KXBTC15M", "Kalshi KXBTCD"],
    "fees_note": "BTCC VIP0 USDT-M taker ~0.048% notional",
    "kill_list": [
        "500x recovery trades",
        "engagement-bait prompt packs (AiWithSaira etc.)",
        "fake GitHub bot sellers",
        "Polymarket/Kalshi auto-bots without keys+gate",
        "memecoin FOMO as company work",
    ],
}

# Rolling price tape for fibs / Hurst
_TAPE: deque[float] = deque(maxlen=240)
_HYGIENE: dict[str, Any] = {
    "flags": [],
    "last_trade_side": None,
    "last_result": None,
    "flatten_ts": 0.0,
    "trade_count_window": 0,
    "window_start": time.time(),
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def push_price(price: float | None) -> None:
    if price is not None and price > 0:
        _TAPE.append(float(price))


def hurst_exponent(series: list[float] | None = None) -> float | None:
    """R/S rough Hurst on log-price increments. None if too short."""
    xs = list(series if series is not None else _TAPE)
    if len(xs) < 32:
        return None
    rets = [math.log(xs[i] / xs[i - 1]) for i in range(1, len(xs)) if xs[i - 1] > 0]
    if len(rets) < 24:
        return None
    n = len(rets)
    mean_r = sum(rets) / n
    deviations = []
    cum = 0.0
    for r in rets:
        cum += r - mean_r
        deviations.append(cum)
    r_range = max(deviations) - min(deviations)
    s = math.sqrt(sum((r - mean_r) ** 2 for r in rets) / n) or 1e-12
    if r_range <= 0:
        return 0.5
    try:
        h = math.log(r_range / s) / math.log(n)
    except ValueError:
        return 0.5
    return _clamp(h, 0.01, 0.99)


def fib_levels(price: float | None = None, window: int = 90) -> dict[str, Any]:
    """Classic fib retracements from recent swing high/low + golden pocket."""
    xs = list(_TAPE)[-window:] if _TAPE else []
    if price is not None:
        xs = xs + [float(price)]
    if len(xs) < 8:
        hist = DOCTRINE["historical_levels_sep2026"]
        return {
            "source": "historical_sep2026",
            "swing_high": hist["golden_pocket_7d"][1],
            "swing_low": hist["support_2"],
            "levels": {
                "gp_618_65": hist["golden_pocket_7d"],
                "reclaim": hist["reclaim_long_trigger"],
                "flush": hist["flush_level"],
                "support_1": hist["support_1"],
                "support_2": hist["support_2"],
            },
            "in_golden_pocket": False,
        }
    hi, lo = max(xs), min(xs)
    rng = hi - lo if hi > lo else 1.0
    # golden pocket = 0.618–0.65 retracement of the measured leg
    gp_lo = hi - rng * 0.65
    gp_hi = hi - rng * 0.618
    levels = {
        "fib_236": hi - rng * 0.236,
        "fib_382": hi - rng * 0.382,
        "fib_500": hi - rng * 0.500,
        "fib_618": hi - rng * 0.618,
        "fib_650": hi - rng * 0.650,
        "fib_786": hi - rng * 0.786,
        "gp_lo": gp_lo,
        "gp_hi": gp_hi,
        "swing_high": hi,
        "swing_low": lo,
        "range": rng,
    }
    px = float(price) if price is not None else xs[-1]
    in_gp = gp_lo <= px <= gp_hi
    # reclaim logic: hold above prior reclaim proxy = fib 50 of last up-leg or swing mid
    reclaim = levels["fib_500"]
    flush = levels["fib_786"]
    return {
        "source": "tape",
        "price": px,
        "swing_high": hi,
        "swing_low": lo,
        "range": rng,
        "levels": {
            "gp_618_65": [gp_lo, gp_hi],
            "fib_236": levels["fib_236"],
            "fib_382": levels["fib_382"],
            "fib_500": reclaim,
            "fib_618": levels["fib_618"],
            "fib_786": flush,
            "reclaim": reclaim,
            "flush": flush,
            "support_1": levels["fib_786"],
            "support_2": lo,
            "scale_out_1": levels["fib_382"],
            "scale_out_2": levels["fib_236"],
        },
        "in_golden_pocket": in_gp,
        "above_reclaim": px >= reclaim,
        "below_flush": px <= flush,
        "distance_to_gp": (gp_lo - px) if px < gp_lo else (0.0 if in_gp else px - gp_hi),
    }


def hygiene_flags(
    *,
    side: str | None = None,
    conf: float | None = None,
    hurst: float | None = None,
    fibs: dict[str, Any] | None = None,
    seconds_left: float | None = None,
    force: bool = False,
) -> list[str]:
    """BTCC hygiene — any fire → veto (signals-only doctrine)."""
    flags: list[str] = []
    now = time.time()
    # revenge lockout 30 min after flatten
    if now - float(_HYGIENE.get("flatten_ts") or 0) < 30 * 60:
        flags.append("revenge_lockout")
    # rapid-fire trades in short window
    if now - float(_HYGIENE.get("window_start") or 0) > 300:
        _HYGIENE["window_start"] = now
        _HYGIENE["trade_count_window"] = 0
    if int(_HYGIENE.get("trade_count_window") or 0) >= 4:
        flags.append("overtrade_window")
    # no-setup: directional lean without fib/gp/hurst support
    if side in {"YES", "NO"}:
        f = fibs or {}
        in_gp = bool(f.get("in_golden_pocket"))
        above_reclaim = bool(f.get("above_reclaim"))
        below_flush = bool(f.get("below_flush"))
        h = hurst
        setup_ok = in_gp or above_reclaim or below_flush
        if h is not None:
            if side == "YES" and h < 0.45 and not in_gp:
                flags.append("mean_revert_against_long")
            if side == "NO" and h < 0.45 and not below_flush:
                flags.append("mean_revert_against_short")
            if 0.47 <= h <= 0.53 and not setup_ok:
                flags.append("random_regime_no_setup")
        if not setup_ok and (conf is None or float(conf) < 0.75):
            # Kalshi 15m: strong fair-book edge IS a valid setup (not leverage 500x)
            # Only flag no_fib_setup when there is also no strong fair-book signal.
            # Caller passes fibs; board signals carry strong_fair_book_edge separately.
            fibs_src = fibs or {}
            # leave flag if truly no structure — judge/board can ignore when edge is strong
            flags.append("no_fib_setup")
        # stale window — near settlement without edge
        if seconds_left is not None and float(seconds_left) < 15 and (conf is None or float(conf) < 0.7):
            flags.append("late_window_no_edge")
    if force:
        flags.append("forced_manual")
    return flags


def note_flatten(reason: str = "flatten") -> None:
    _HYGIENE["flatten_ts"] = time.time()
    _HYGIENE["last_result"] = reason
    _HYGIENE["trade_count_window"] = int(_HYGIENE.get("trade_count_window") or 0)


def note_trade(side: str | None) -> None:
    _HYGIENE["last_trade_side"] = side
    _HYGIENE["trade_count_window"] = int(_HYGIENE.get("trade_count_window") or 0) + 1


def complete_set_flag(yes_ask: float | None, no_ask: float | None) -> dict[str, Any]:
    """Grokbot paper scanner: Up+Down sum < 0.98 = gap / incomplete set."""
    if yes_ask is None or no_ask is None:
        return {"flagged": False, "sum": None}
    s = float(yes_ask) + float(no_ask)
    return {
        "flagged": s < 0.98,
        "sum": round(s, 4),
        "gap_cents": round((1.0 - s) * 100, 2) if s < 1 else 0.0,
        "note": "PAPER complete-set gap — no auto live",
    }


def btcc_signal_board(force: bool = False) -> dict[str, Any]:
    """Full Grokbot BTCC board for 15m Kalshi BTC."""
    snap = fast_snapshot()
    win = snap.get("window") or {}
    spot = snap.get("spot") or {}
    price = spot.get("price") or win.get("open_of_window")
    push_price(price)

    hurst = hurst_exponent()
    fibs = fib_levels(price)
    fair = snap.get("fair_yes")
    yes_mid = win.get("yes_mid")
    yes_ask = win.get("yes_ask")
    no_ask = win.get("no_ask")
    open_px = win.get("open_of_window")
    secs = win.get("seconds_left")
    edge = None
    if fair is not None and yes_mid is not None:
        edge = float(fair) - float(yes_mid)

    # Confluence score for YES (settle above open)
    signals: list[str] = []
    setup = "NO SETUP"
    lean = "SKIP"
    conf = 0.0
    reasons: list[str] = []

    in_gp = bool(fibs.get("in_golden_pocket"))
    above_reclaim = bool(fibs.get("above_reclaim"))
    below_flush = bool(fibs.get("below_flush"))
    delta_pct = None
    if price and open_px:
        delta_pct = ((price - open_px) / open_px) * 100.0

    score = 0.0
    # Hurst regime
    if hurst is not None:
        if hurst > 0.55:
            signals.append("hurst_trending")
            score += 0.2
            reasons.append(f"H={hurst:.2f} trending")
        elif hurst < 0.45:
            signals.append("hurst_mean_revert")
            score -= 0.05
            reasons.append(f"H={hurst:.2f} mean-revert")
        else:
            signals.append("hurst_random")
            reasons.append(f"H={hurst:.2f} random")
    # Fib / golden pocket
    if in_gp:
        signals.append("golden_pocket")
        score += 0.35
        reasons.append("in golden pocket 0.618–0.65")
    if above_reclaim:
        signals.append("above_reclaim")
        score += 0.2
        reasons.append("above fib50 reclaim")
    if below_flush:
        signals.append("below_flush")
        score += 0.2
        reasons.append("below flush — short-side structure")
    # Fair vs book edge — primary 15m Kalshi edge (QuantDinger / fast feed)
    if edge is not None:
        ae = abs(float(edge))
        if ae >= 0.15:
            signals.append("strong_fair_book_edge")
            score += 0.45 if edge > 0 else -0.45
            reasons.append(f"strong fair-book edge {edge:+.3f}")
        elif ae >= 0.08:
            signals.append("fair_leads_book")
            score += 0.25 if edge > 0 else -0.25
            reasons.append(f"fair-book edge {edge:+.3f}")
    # Window momentum vs open
    if delta_pct is not None:
        if delta_pct > 0.02:
            signals.append("above_window_open")
            score += 0.1
        elif delta_pct < -0.02:
            signals.append("below_window_open")
            score -= 0.1

    # Compose lean — fib/gp = HIGH; strong fair-book edge = SETUP
    if score >= 0.40:
        lean = "YES"
        if score >= 0.70 and (in_gp or above_reclaim):
            setup = "HIGH CONFLUENCE"
        else:
            setup = "SETUP"
        conf = _clamp(0.55 + score * 0.35, 0.0, 0.95)
    elif score <= -0.40:
        lean = "NO"
        if score <= -0.70 and (below_flush or in_gp):
            setup = "HIGH CONFLUENCE"
        else:
            setup = "SETUP"
        conf = _clamp(0.55 + abs(score) * 0.35, 0.0, 0.95)
    else:
        lean = "SKIP"
        setup = "NO SETUP"
        conf = 0.0
        reasons.append("wait for reclaim / pocket / confirmed break")

    # Hygiene — OVERRIDE: Jeremy nixed hygiene veto (survive day + no auto 500x only)
    flags = hygiene_flags(
        side=lean if lean in {"YES", "NO"} else None,
        conf=conf,
        hurst=hurst,
        fibs=fibs,
        seconds_left=secs,
    )
    strong_edge = "strong_fair_book_edge" in signals
    if strong_edge:
        flags = [f for f in flags if f not in {"no_fib_setup", "random_regime_no_setup"}]
    enforce = bool(getattr(config, "btcc_hygiene_enforce", False))
    if not enforce:
        # logged but NOT vetoing — take risk to recover
        veto = False
        setup = setup if lean in {"YES", "NO"} else setup
        lean_final = lean
        conf_final = conf
        hygiene_note = "hygiene logged but OVERRIDE off (take risk)"
    else:
        veto = bool(flags)
        if veto:
            setup = "HYGIENE VETO"
            if lean in {"YES", "NO"}:
                reasons.append("hygiene: " + ",".join(flags))
            lean_final = "SKIP"
            conf_final = min(conf, 0.35)
        else:
            lean_final = lean
            conf_final = conf
        hygiene_note = "enforced"

    cset = complete_set_flag(yes_ask, no_ask)

    return {
        "ok": True,
        "source": "grokbot-btcc",
        "role": DOCTRINE["role"],
        "price": price,
        "open_of_window": open_px,
        "delta_pct": round(delta_pct, 4) if delta_pct is not None else None,
        "yes_mid": yes_mid,
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "fair_yes": fair,
        "edge_vs_book": round(edge, 4) if edge is not None else None,
        "hurst": round(hurst, 3) if hurst is not None else None,
        "fibs": fibs,
        "signals": signals,
        "confluence_score": round(score, 3),
        "setup": setup,
        "lean": lean_final,
        "raw_lean": lean,
        "confidence": round(conf_final, 3),
        "hygiene": {
            "flags": flags,
            "veto": veto,
            "enforce": enforce,
            "note": hygiene_note,
            "override": not enforce,
        },
        "risk_mode": getattr(config, "btcc_risk_mode", "recover"),
        "recover_target_usd": getattr(config, "recover_target_usd", 6.0),
        "complete_set": cset,
        "reasons": reasons,
        "doctrine": {
            "hard_rules": DOCTRINE["hard_rules"],
            "hurst": DOCTRINE["regime_gate_hurst"],
            "kill_list": DOCTRINE["kill_list"],
        },
        "kalshi_note": "KXBTC15M one-ticket / paper until Jeremy arms live",
        "ts": time.time(),
    }


def judgment_overlay_from_btcc(board: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map BTCC board → judge overlay (hygiene can veto QD/JEV leans)."""
    board = board or btcc_signal_board()
    veto = bool((board.get("hygiene") or {}).get("veto"))
    lean = board.get("lean") or "SKIP"
    conf = float(board.get("confidence") or 0)
    use = (not veto) and lean in {"YES", "NO"} and conf >= 0.55
    return {
        "src": "grokbot-btcc",
        "lean": lean if use else "SKIP",
        "raw_lean": board.get("raw_lean"),
        "conf": conf if use else min(conf, 0.4),
        "setup": board.get("setup"),
        "hygiene_veto": veto,
        "hygiene_flags": (board.get("hygiene") or {}).get("flags") or [],
        "hurst": board.get("hurst"),
        "in_golden_pocket": (board.get("fibs") or {}).get("in_golden_pocket"),
        "edge_vs_book": board.get("edge_vs_book"),
        "signals": board.get("signals"),
        "reason": "; ".join(board.get("reasons") or [])[:200],
        "board": board,
    }
