"""Bitcoin listings from JerBouma/FinanceDatabase.

The catalog is symbols and categories, not prices. It is loaded once and
does not place orders. A missing install leaves the desk alone.
"""
from __future__ import annotations

from typing import Any

_CACHE: dict[str, Any] | None = None


def btc_listings(limit: int = 12) -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        import financedatabase as fd
    except ImportError:
        _CACHE = {"ok": False, "error": "financedatabase is not installed", "source": "JerBouma/FinanceDatabase"}
        return _CACHE
    try:
        frame = fd.Cryptos().data
        # The catalog's code for Bitcoin is BTC2 (BTC-USD is not in the file).
        bitcoin = frame[frame["cryptocurrency"].astype(str) == "BTC2"]
        symbols = sorted(str(symbol) for symbol in bitcoin.index)
    except Exception as exc:  # noqa: BLE001
        _CACHE = {"ok": False, "error": str(exc)[:160], "source": "JerBouma/FinanceDatabase"}
        return _CACHE
    _CACHE = {
        "ok": True,
        "source": "JerBouma/FinanceDatabase",
        "n": len(symbols),
        "symbols": symbols[:limit],
    }
    return _CACHE
