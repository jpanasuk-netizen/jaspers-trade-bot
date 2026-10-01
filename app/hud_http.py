"""HUD HTTP in its own process so the trading loops cannot stall the page."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML_PATH = Path(__file__).with_name("ui.html")
HUD_JSON = Path(__file__).resolve().parent.parent / "data" / "hud.json"
ETH_LOG = Path(__file__).resolve().parent.parent / "eth_desk" / "data" / "orders.jsonl"
BTC_LEDGER = Path(__file__).resolve().parent.parent / "data" / "spin_ledger.jsonl"
ETH_STATUS = "http://127.0.0.1:3010/"
ETH_KLINES = "https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval={interval}&limit={limit}"
_chart_cache: dict = {"at": 0.0, "body": b""}


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


class Handler(BaseHTTPRequestHandler):
    server_version = "JevHud/1.0"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            origin = (self.headers.get("Origin") or "").strip()
            if origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost"):
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path.split("?", 1)[0] or "/").rstrip("/") or "/"
        if path in {"/", "/index.html", "/hud", "/trading"}:
            html = HTML_PATH.read_bytes() if HTML_PATH.is_file() else b"<h1>missing ui.html</h1>"
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._send(200, b'{"ok":true,"name":"Jasper HUD"}', "application/json")
            return
        if path == "/api/state":
            if HUD_JSON.is_file():
                self._send(200, HUD_JSON.read_bytes(), "application/json")
            else:
                self._send(200, b'{"connection":"starting"}', "application/json")
            return
        if path == "/api/eth":
            self._send(200, _eth_status(), "application/json")
            return
        if path == "/api/eth-chart":
            self._send(200, _eth_chart(), "application/json")
            return
        if path == "/api/btc":
            self._send(200, json.dumps({"ok": True, "rows": _btc_rows()}).encode("utf-8"), "application/json")
            return
        self._send(404, b'{"ok":false}', "application/json")


def _eth_status() -> bytes:
    """Live ETH desk snapshot. A down desk must not stall the Bitcoin page."""
    try:
        req = urllib.request.Request(ETH_STATUS, headers={"User-Agent": "jev-hud/1.0"})
        with urllib.request.urlopen(req, timeout=0.6) as resp:
            raw = resp.read(8192)
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, dict):
            parsed.pop("market", None)
            parsed["ok"] = True
            parsed["rows"] = _eth_rows()
            return json.dumps(parsed).encode("utf-8")
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
        reason = str(exc)[:160]
    else:
        reason = "empty eth status"
    return json.dumps(
        {
            "ok": False,
            "desk": "eth",
            "series": "KXETH15M",
            "action": "down",
            "reason": reason,
            "rows": _eth_rows(),
        }
    ).encode("utf-8")


def _klines(interval: str, limit: int) -> list[dict]:
    url = ETH_KLINES.format(interval=interval, limit=limit)
    req = urllib.request.Request(url, headers={"User-Agent": "jev-hud/1.0"})
    with urllib.request.urlopen(req, timeout=2.5) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    bars: list[dict] = []
    if not isinstance(rows, list):
        return bars
    for row in rows:
        opened = int(row[0])
        if opened > 100_000_000_000_000:
            opened //= 1000
        bars.append({"t": opened, "o": float(row[1]), "c": float(row[4])})
    return bars


def _eth_chart_fresh() -> bytes:
    """ETHUSDT graphs for the HUD. Prices stay on the page; no market book."""
    now_ms = int(time.time() * 1000)
    window = now_ms - (now_ms % 900_000)
    one = _klines("1m", 60)
    fifteen = _klines("15m", 32)
    open_px = None
    for bar in fifteen:
        if bar["t"] == window:
            open_px = bar["o"]
            break
    if open_px is None and fifteen:
        open_px = fifteen[-1]["o"]
    payload = {
        "ok": True,
        "symbol": "ETHUSDT",
        "open": open_px,
        "m1": [bar["c"] for bar in one],
        "m15": [bar["c"] for bar in fifteen],
        "bodies": [round(bar["c"] - bar["o"], 4) for bar in fifteen],
    }
    return json.dumps(payload).encode("utf-8")


def _eth_chart() -> bytes:
    """Cached so the page poll does not hammer the candle host or stall Bitcoin."""
    now = time.monotonic()
    cached = _chart_cache["body"]
    if cached and now - _chart_cache["at"] < 8:
        return cached
    try:
        body = _eth_chart_fresh()
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError, KeyError, IndexError) as exc:
        if cached:
            return cached
        reason = f"candle feed {type(exc).__name__}"[:160]
        return json.dumps({"ok": False, "symbol": "ETHUSDT", "reason": reason}).encode("utf-8")
    _chart_cache["at"] = now
    _chart_cache["body"] = body
    return body


def _eth_rows(limit: int = 40) -> list:
    """Recent ETH desk decisions for the left-hand log. No market book."""
    if not ETH_LOG.is_file():
        return []
    rows: list = []
    try:
        lines = ETH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        sig = raw.get("signal") if isinstance(raw.get("signal"), dict) else {}
        rows.append(
            {
                "ts": raw.get("ts"),
                "window_open": raw.get("window_open"),
                "action": raw.get("action"),
                "reason": raw.get("reason"),
                "rule": sig.get("rule"),
                "side": sig.get("side"),
                "run": sig.get("run"),
                "filled": bool(raw.get("filled")),
                "ticker": raw.get("ticker"),
            }
        )
    rows.reverse()
    return rows[:limit]


def _btc_rows(limit: int = 40) -> list:
    """Recent Bitcoin desk rows for the log beside ETH. No prices."""
    if not BTC_LEDGER.is_file():
        return []
    try:
        lines = BTC_LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "ts": raw.get("ts"),
                "side": raw.get("side"),
                "result": raw.get("result"),
                "reason": raw.get("reason") or raw.get("spin_reason"),
                "ticker": raw.get("ticker"),
                "mode": raw.get("mode"),
                "won": raw.get("won"),
                "conf": raw.get("conf"),
            }
        )
    rows.reverse()
    return rows


def serve(host: str = "0.0.0.0", port: int = 3000) -> None:
    HUD_JSON.parent.mkdir(parents=True, exist_ok=True)
    httpd = Server((host, port), Handler)
    print(f"[hud-http] {host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
