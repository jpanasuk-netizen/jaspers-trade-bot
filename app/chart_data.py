"""Rolling chart series for the trading HUD (BTC / Kalshi / models)."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

_LOCK = threading.Lock()
_MAX = 240

_SPOT: deque[dict[str, Any]] = deque(maxlen=_MAX)
_BOOK: deque[dict[str, Any]] = deque(maxlen=_MAX)
_MODELS: deque[dict[str, Any]] = deque(maxlen=_MAX)


def record_tick(
    *,
    price: float | None,
    yes_mid: float | None,
    yes_bid: float | None,
    yes_ask: float | None,
    no_ask: float | None,
    fair_yes: float | None,
    edge: float | None,
    signal: float | None,
    side: str | None,
    conf: float | None,
    open_of_window: float | None = None,
) -> None:
    ts = time.time()
    above = None
    if price is not None and open_of_window:
        try:
            above = 1 if float(price) > float(open_of_window) else 0
        except (TypeError, ValueError):
            above = None
    with _LOCK:
        if price is not None:
            _SPOT.append({"t": ts, "v": float(price), "open": open_of_window})
        if yes_mid is not None or yes_ask is not None:
            _BOOK.append(
                {
                    "t": ts,
                    "yes_mid": yes_mid,
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_ask": no_ask,
                    "price": price,
                    "open": open_of_window,
                }
            )
        _MODELS.append(
            {
                "t": ts,
                "fair_yes": fair_yes,
                "book_yes": yes_mid,
                "edge": edge,
                "signal": signal,
                "side": side,
                "conf": conf,
                "price": price,
                "open": open_of_window,
                "above_open": above,
            }
        )


def chart_series() -> dict[str, Any]:
    with _LOCK:
        return {
            "spot": list(_SPOT),
            "book": list(_BOOK),
            "models": list(_MODELS),
            "count": len(_SPOT),
        }
