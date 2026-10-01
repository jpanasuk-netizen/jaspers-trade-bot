"""Live ETH 15-minute desk.

Shares the Kalshi predictions balance with the Bitcoin desk and leaves that
desk its next clip. Bitcoin YES/NO stays with Jev. This process only sends
KXETH15M, and only when the sealed ETH streak fade is on and the ask still
clears a 57% fee-adjusted breakeven.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import config  # noqa: E402
from app.kalshi_live import (  # noqa: E402
    contract_quote,
    fetch_positions,
    place_order,
    taker_fee_usd,
)
from app.martingale import kalshi_cash  # noqa: E402
from eth_desk.signal import fade_signal, price_ok, shared_budget  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
STATE_PATH = DATA / "state.json"
LOG_PATH = DATA / "orders.jsonl"
SERIES = "KXETH15M"
BINANCE = "https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=15m&limit=30"
BAR_MS = 900_000
ENTRY_SEC = 120
HOST = "127.0.0.1"
PORT = 3010

_status: dict[str, Any] = {"desk": "eth", "series": SERIES, "note": "starting"}
_status_lock = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_status(patch: dict[str, Any]) -> None:
    public = {k: v for k, v in patch.items() if k != "market"}
    with _status_lock:
        _status.clear()
        _status.update(public)
        _status["desk"] = "eth"
        _status["series"] = SERIES
        _status["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "market"}


def _log(row: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_public_row(row), sort_keys=True) + "\n")


def live_armed() -> bool:
    mark = config.live_mark
    if not mark.is_file():
        return False
    try:
        word = mark.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return False
    return word in {"live", "1", "go", "yes", "true"}


def _colors(now_ms: int) -> tuple[list[int] | None, str]:
    try:
        return closed_colors(now_ms), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"candle feed {type(exc).__name__}"[:160]


def closed_colors(now_ms: int) -> list[int]:
    req = urllib.request.Request(BINANCE, headers={"User-Agent": "eth-desk/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    colors: list[int] = []
    for row in rows:
        opened = int(row[0])
        if opened > 100_000_000_000_000:
            opened //= 1000
        if opened + BAR_MS > now_ms - 2_000:
            continue
        open_px = float(row[1])
        close_px = float(row[4])
        if close_px > open_px:
            colors.append(1)
        elif close_px < open_px:
            colors.append(-1)
        else:
            colors.append(0)
    return colors


def open_market() -> dict[str, Any] | None:
    from app.kalshi_live import _kreq, load_creds

    key_id, pk = load_creds()
    status, payload = _kreq(
        key_id,
        pk,
        "GET",
        f"/trade-api/v2/markets?limit=5&series_ticker={SERIES}&status=open",
    )
    if status != 200 or not isinstance(payload, dict):
        return None
    for market in payload.get("markets") or []:
        ticker = str(market.get("ticker") or "")
        if ticker.startswith(SERIES):
            return market
    return None


def _clip_usd() -> float:
    return float(getattr(config, "stake_usd", 2.0) or 2.0)


def _take_pay(ask: float) -> float:
    return min(0.99, round(float(ask) + 0.01, 2))


def _remember(row: dict[str, Any]) -> None:
    state = _read_state()
    state["last_window"] = row.get("window_open")
    state["last"] = _public_row(row)
    _write_state(state)
    _log({"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **_public_row(row)})


def evaluate(now_ms: int) -> dict[str, Any]:
    window = now_ms - (now_ms % BAR_MS)
    age = (now_ms - window) / 1000.0
    out: dict[str, Any] = {
        "window_open": _iso(window),
        "age_sec": round(age, 1),
        "action": "wait",
    }
    if age > ENTRY_SEC:
        out["action"] = "missed"
        out["reason"] = "past the entry minute"
        colors, err = _colors(now_ms)
        if colors is None:
            out["reason"] = err or "candle feed down"
            return out
        signal = fade_signal(colors)
        if signal:
            out["signal"] = {k: signal[k] for k in ("rule", "side", "run", "half_kelly")}
        else:
            out["reason"] = "past the entry minute, streak under 5"
        return out
    colors, err = _colors(now_ms)
    if colors is None:
        out["action"] = "wait"
        out["reason"] = err or "candle feed down"
        return out
    signal = fade_signal(colors)
    out["closed_bars"] = len(colors)
    if signal is None:
        if age < 20:
            out["action"] = "wait"
            out["reason"] = "waiting for the closed candle"
            return out
        out["action"] = "flat"
        out["reason"] = "streak under 5"
        return out
    out["signal"] = {k: signal[k] for k in ("rule", "side", "run", "half_kelly")}
    if not live_armed():
        out["action"] = "skip"
        out["reason"] = "live mark is off"
        return out
    if _read_state().get("last_window") == out["window_open"]:
        out["action"] = "done"
        out["reason"] = "already acted this window"
        return out
    market = open_market()
    if not market:
        out["action"] = "wait"
        out["reason"] = "no open KXETH15M market"
        return out
    ticker = str(market.get("ticker") or "")
    if not ticker.startswith(SERIES):
        out["action"] = "skip"
        out["reason"] = "refusing a non-ETH ticker"
        return out
    side = str(signal["side"])
    quote = contract_quote(side, market)
    if not quote:
        out["action"] = "wait"
        out["reason"] = "no ask yet"
        return out
    cash = kalshi_cash()
    if cash is None:
        out["action"] = "wait"
        out["reason"] = "balance unread"
        return out
    budget = shared_budget(float(cash), float(signal["half_kelly"]), _clip_usd())
    out["cash"] = round(float(cash), 4)
    out["budget"] = budget
    out["ticker"] = ticker
    out["market"] = market
    if budget < 0.02:
        out["action"] = "skip"
        out["reason"] = "shared cash is reserved for the bitcoin clip"
        return out
    pay = _take_pay(float(quote["ask"]))
    count = max(0.01, round(budget / pay, 2))
    fee = taker_fee_usd(pay, count)
    while count >= 0.01 and (count * pay + fee) > budget + 1e-9:
        count = round(count - 0.01, 2)
        fee = taker_fee_usd(pay, count)
    out["pay"] = pay
    out["count"] = count
    out["fee"] = fee
    if count < 0.01 or not price_ok(pay, count, fee):
        out["action"] = "skip"
        out["reason"] = "ask does not clear 57% after the fee"
        return out
    held = fetch_positions().get(ticker) or {}
    if abs(float(held.get("count") or 0)) >= 0.01:
        out["action"] = "skip"
        out["reason"] = "position already open"
        return out
    out["action"] = "send"
    return out


def act(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("action") != "send":
        if row.get("action") in {"skip", "flat", "missed"}:
            if _read_state().get("last_window") != row.get("window_open"):
                _remember(row)
        return row
    market = row.get("market")
    if not isinstance(market, dict):
        row["action"] = "wait"
        row["reason"] = "market missing"
        return row
    try:
        result = place_order(
            str(row["ticker"]),
            str(row["signal"]["side"]),
            market,
            stake_usd=float(row["budget"]),
        )
        row["filled"] = bool(result.get("filled"))
        row["fill_count"] = result.get("fill_count")
        row["fill_price"] = result.get("fill_price")
        row["reason"] = "filled" if row["filled"] else "sent, no fill"
    except Exception as exc:  # noqa: BLE001
        row["action"] = "error"
        row["reason"] = str(exc)[:300]
        row["filled"] = False
    _remember(row)
    return row


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        with _status_lock:
            body = json.dumps(_status, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _serve() -> None:
    server = ThreadingHTTPServer((HOST, PORT), _Handler)
    server.serve_forever()


def main() -> None:
    threading.Thread(target=_serve, daemon=True).start()
    print(f"ETH desk on http://{HOST}:{PORT} series={SERIES}", flush=True)
    while True:
        try:
            row = act(evaluate(_now_ms()))
            _set_status(row)
            print(
                f"{row.get('window_open')} {row.get('action')} {row.get('reason', '')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            _set_status({"action": "error", "reason": str(exc)[:300]})
            print(f"loop {type(exc).__name__}: {exc}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
