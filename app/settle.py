"""Did the 15-min YES/NO ticket pay? Cached Kalshi market.result."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from .config import config

_CACHE: dict[str, str] = {}


def _cache_path() -> Path:
    return config.data_dir / "settlements.json"


def _load() -> dict[str, str]:
    global _CACHE
    if _CACHE:
        return _CACHE
    p = _cache_path()
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _CACHE = {str(k): str(v).upper() for k, v in raw.items() if str(v).upper() in {"YES", "NO"}}
        except Exception:  # noqa: BLE001
            _CACHE = {}
    return _CACHE


def _save() -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_CACHE, indent=0), encoding="utf-8")


def outcome_side(ticker: str | None) -> str | None:
    if not ticker:
        return None
    cache = _load()
    hit = cache.get(ticker)
    if hit in {"YES", "NO"}:
        return hit
    url = f"https://external-api.kalshi.com/trade-api/v2/markets/{ticker}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode() or "{}")
    except Exception:  # noqa: BLE001
        return None
    m = data.get("market") if isinstance(data.get("market"), dict) else data
    raw = str(m.get("result") or m.get("result_side") or "").strip().upper()
    if raw in {"YES", "NO"}:
        cache[ticker] = raw
        _CACHE = cache
        _save()
        return raw
    return None


def attach_outcome(rec: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(rec, dict):
        return {}
    out = dict(rec)
    side = str(out.get("side") or "").upper()
    settled = outcome_side(str(out.get("ticker") or ""))
    out["outcome_side"] = settled
    if settled in {"YES", "NO"} and side in {"YES", "NO"}:
        out["won"] = side == settled
    else:
        out["won"] = None
    return out
