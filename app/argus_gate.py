"""Argus promotion gates for the live desk.

From velesxbt/argus (https://x.com/velesxbt/status/2099531351225426277):
a book is promotable only if Sharpe, drawdown, hit rate, and t-stat all
clear on data the rule was not fit on, and then again on a sealed vault.
Failing the gates does not stop the current $2 spin. It refuses a larger size.
The model does not get to claim it passed.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from .config import config

SHARPE_MIN = 1.5
MAX_DD = 0.15
HIT_MIN = 0.55
T_MIN = 2.0
# research 85%, of which the last 30% is the validator. Final 15% is the vault.
VAULT_FRACTION = 0.15
OOS_OF_RESEARCH = 0.30
MIN_EACH = 4
_CACHE: dict[str, Any] = {"ts": 0.0, "report": None}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sharpe(returns: list[float], periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    sd = _std(returns)
    if sd <= 0:
        return 0.0
    return _mean(returns) / sd * math.sqrt(max(periods_per_year, 1.0))


def max_drawdown(returns: list[float]) -> float:
    eq = 1.0
    peak = 1.0
    worst = 0.0
    for r in returns:
        eq *= max(0.0, 1.0 + r)
        if eq <= 0:
            return 1.0
        peak = max(peak, eq)
        worst = max(worst, 1.0 - eq / peak)
    return worst


def hit_rate(returns: list[float]) -> float:
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns)


def t_stat(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    sd = _std(returns)
    if sd <= 0:
        return 0.0
    return _mean(returns) / (sd / math.sqrt(len(returns)))


def _periods_per_year(stamps: list[float], n: int) -> float:
    if n < 2 or len(stamps) < 2:
        return float(max(n, 1))
    span = max(stamps) - min(stamps)
    if span < 3600:
        return float(n)
    per_year = n / span * (365 * 86400)
    return max(1.0, min(per_year, 365 * 24 * 4))


def grade_slice(returns: list[float], periods_per_year: float) -> dict[str, Any]:
    gates = {
        "sharpe": {"value": round(sharpe(returns, periods_per_year), 3), "need": f"> {SHARPE_MIN}"},
        "max_drawdown": {"value": round(max_drawdown(returns), 3), "need": f"< {MAX_DD}"},
        "hit_rate": {"value": round(hit_rate(returns), 3), "need": f"> {HIT_MIN}"},
        "t_stat": {"value": round(t_stat(returns), 3), "need": f"> {T_MIN}"},
    }
    ok = (
        len(returns) >= MIN_EACH
        and gates["sharpe"]["value"] > SHARPE_MIN
        and gates["max_drawdown"]["value"] < MAX_DD
        and gates["hit_rate"]["value"] > HIT_MIN
        and gates["t_stat"]["value"] > T_MIN
    )
    gates["sharpe"]["pass"] = gates["sharpe"]["value"] > SHARPE_MIN and len(returns) >= 2
    gates["max_drawdown"]["pass"] = gates["max_drawdown"]["value"] < MAX_DD
    gates["hit_rate"]["pass"] = gates["hit_rate"]["value"] > HIT_MIN
    gates["t_stat"]["pass"] = gates["t_stat"]["value"] > T_MIN and len(returns) >= 2
    return {"n": len(returns), "pass": ok, "gates": gates}


def split_returns(rows: list[tuple[float, float]]) -> tuple[list[float], list[float], float]:
    """rows are (unix_ts, return), oldest first. Returns (oos, vault, ppy)."""
    rows = sorted(rows, key=lambda x: x[0])
    n = len(rows)
    n_vault = max(MIN_EACH, int(round(n * VAULT_FRACTION)))
    n_vault = min(n_vault, n // 3)
    research = rows[: n - n_vault]
    vault = rows[n - n_vault :]
    n_oos = max(MIN_EACH, int(round(len(research) * OOS_OF_RESEARCH)))
    n_oos = min(n_oos, max(0, len(research) - MIN_EACH))
    oos = research[len(research) - n_oos :]
    stamps = [t for t, _ in rows]
    return [r for _, r in oos], [r for _, r in vault], _periods_per_year(stamps, n)


def judge_returns(rows: list[tuple[float, float]]) -> dict[str, Any]:
    """Validator grades OOS. Checker re-grades the vault. Both must pass."""
    if len(rows) < MIN_EACH * 3:
        report = {
            "promote": False,
            "reason": f"not enough settled trades ({len(rows)}) to split a vault",
            "n": len(rows),
            "source": "velesxbt/argus",
        }
        return report
    oos, vault, ppy = split_returns(rows)
    validator = grade_slice(oos, ppy)
    checker = grade_slice(vault, ppy)
    promote = bool(validator["pass"] and checker["pass"])
    if promote:
        reason = "validator and checker both passed; a larger size is allowed"
    elif not validator["pass"]:
        reason = "validator failed the out-of-sample gates; size stays put"
    else:
        reason = "checker failed the sealed vault; size stays put"
    return {
        "promote": promote,
        "reason": reason,
        "n": len(rows),
        "periods_per_year": round(ppy, 1),
        "validator": validator,
        "checker": checker,
        "source": "velesxbt/argus",
        "rules": "no agent grades its own sample; vault is unseen",
    }


def _trade_return(rec: dict[str, Any], won: bool) -> float | None:
    try:
        cost = float(rec.get("stake_usd") or 0)
    except (TypeError, ValueError):
        return None
    if cost <= 0:
        return None
    from .spin import fill_pnl

    return fill_pnl(rec, won) / cost


def _settled_rows(ledger: Path) -> list[tuple[float, float]]:
    from .settle import attach_outcome

    out: list[tuple[float, float]] = []
    if not ledger.is_file():
        return out
    for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("result") != "LIVE_FILLED" or not rec.get("filled"):
            continue
        settled = attach_outcome(rec)
        won = settled.get("won")
        if won is None:
            continue
        ret = _trade_return(rec, bool(won))
        if ret is None:
            continue
        ts = rec.get("ts") or ""
        try:
            from datetime import datetime

            stamp = datetime.fromisoformat(str(ts)).timestamp()
        except ValueError:
            stamp = float(len(out))
        out.append((stamp, ret))
    return out


def promotion_report(force: bool = False) -> dict[str, Any]:
    now = time.time()
    cached = _CACHE.get("report")
    if not force and isinstance(cached, dict) and now - float(_CACHE.get("ts") or 0) < 120:
        return cached
    ledger = config.data_dir / "spin_ledger.jsonl"
    report = judge_returns(_settled_rows(ledger))
    report["checked_at"] = now
    _CACHE["ts"] = now
    _CACHE["report"] = report
    try:
        path = config.data_dir / "argus_report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        pass
    return report
