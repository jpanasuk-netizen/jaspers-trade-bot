"""Standalone decision-history site on :3002.

Reads the local spin ledger / scoreboard / martingale. No secrets.
"""
from __future__ import annotations

import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import config
from .spin import live_armed

HTML_PATH = Path(__file__).with_name("history_desk.html")
PORT = int(__import__("os").environ.get("HISTORY_PORT", "3002"))
HOST = __import__("os").environ.get("HISTORY_HOST", "127.0.0.1")


def _ledger_path() -> Path:
    return config.data_dir / "spin_ledger.jsonl"


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _iter_ledger():
    path = _ledger_path()
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:  # noqa: BLE001
                continue


def _row_view(r: dict[str, Any]) -> dict[str, Any]:
    j = r.get("judge") or {}
    k = r.get("kalshi") or {}
    g = r.get("gates") or {}
    bumped = r.get("stake_bumped") or {}
    q = r.get("quote") or {}
    risk = r.get("risk_gate") or r.get("risk") or {}
    return {
        "ts": r.get("ts"),
        "mode": r.get("mode"),
        "ticker": r.get("ticker"),
        "window_id": r.get("window_id"),
        "seconds_left": r.get("seconds_left"),
        "spot": r.get("spot"),
        "open_of_window": r.get("open_of_window"),
        "delta_from_open": r.get("delta_from_open"),
        "side": r.get("side"),
        "result": r.get("result"),
        "reason": r.get("reason") or r.get("spin_reason"),
        "conf": r.get("conf"),
        "edge": r.get("edge"),
        "entry": r.get("entry"),
        "stake_usd": r.get("stake_usd"),
        "win_pay": r.get("win_pay"),
        "filled": bool(r.get("filled")),
        "judge_src": j.get("src") or j.get("judge_src"),
        "route": j.get("route"),
        "trade_action": j.get("trade_action"),
        "yes_ask": k.get("yes_ask"),
        "no_ask": k.get("no_ask"),
        "yes_mid": k.get("yes_mid"),
        "cash": g.get("cash") or bumped.get("cash"),
        "lots": bumped.get("lots"),
        "need": bumped.get("need") or q.get("need"),
        "ask": bumped.get("entry") or q.get("ask"),
        "risk_verdict": risk.get("verdict"),
        "risk_reasons": risk.get("reasons") or [],
    }


def summarize() -> dict[str, Any]:
    results: Counter[str] = Counter()
    sides: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    windows: set[str] = set()
    n = 0
    fills = 0
    first = last = None
    confs: list[float] = []
    for r in _iter_ledger():
        n += 1
        res = str(r.get("result") or "UNKNOWN")
        results[res] += 1
        sides[str(r.get("side") or "—")] += 1
        modes[str(r.get("mode") or "—")] += 1
        t = r.get("ticker")
        if t:
            windows.add(str(t))
        ts = r.get("ts")
        if ts:
            first = first or ts
            last = ts
        if r.get("filled") or res in {"LIVE_FILLED", "PAPER_FILLED"}:
            fills += 1
        c = r.get("conf")
        if isinstance(c, (int, float)):
            confs.append(float(c))
    return {
        "n": n,
        "fills": fills,
        "windows": len(windows),
        "first_ts": first,
        "last_ts": last,
        "results": dict(results.most_common()),
        "sides": dict(sides),
        "modes": dict(modes),
        "mean_conf": round(sum(confs) / len(confs), 4) if confs else None,
        "liveArmed": live_armed(),
        "scoreboard": _load_json(config.data_dir / "scoreboard.json", {}),
        "martingale": _load_json(config.data_dir / "martingale.json", {}),
        "spun": _load_json(config.data_dir / "spun_windows.json", {}),
        "desk": f"http://{config.host}:{config.port}/",
    }


def history(limit: int = 400, result: str | None = None, side: str | None = None, mode: str | None = None) -> list[dict[str, Any]]:
    rows = [_row_view(r) for r in _iter_ledger()]
    rows.reverse()
    if result:
        want = result.upper()
        rows = [r for r in rows if str(r.get("result") or "").upper() == want]
    if side:
        want = side.upper()
        rows = [r for r in rows if str(r.get("side") or "").upper() == want]
    if mode:
        want = mode.upper()
        rows = [r for r in rows if str(r.get("mode") or "").upper() == want]
    return rows[: max(1, min(int(limit), 2000))]


def _json(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _html(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "JasperHistory/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[hist] {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        if path in {"/", "/history", "/index.html"}:
            html = HTML_PATH.read_text(encoding="utf-8") if HTML_PATH.is_file() else "<h1>missing history_desk.html</h1>"
            _html(self, html)
            return
        if path == "/api/summary":
            _json(self, 200, {"ok": True, **summarize()})
            return
        if path == "/api/history":
            try:
                limit = int((qs.get("limit") or ["400"])[0])
            except (TypeError, ValueError):
                limit = 400
            result = (qs.get("result") or [None])[0]
            side = (qs.get("side") or [None])[0]
            mode = (qs.get("mode") or [None])[0]
            rows = history(limit, result, side, mode)
            _json(self, 200, {"ok": True, "n": len(rows), "rows": rows})
            return
        if path == "/api/martingale":
            _json(self, 200, {"ok": True, "martingale": _load_json(config.data_dir / "martingale.json", {})})
            return
        if path == "/api/scoreboard":
            _json(self, 200, {"ok": True, "scoreboard": _load_json(config.data_dir / "scoreboard.json", {})})
            return
        if path == "/api/health":
            _json(self, 200, {"ok": True, "name": "Jasper's Trade Bot history", "port": PORT, "liveArmed": live_armed()})
            return
        _json(self, 404, {"ok": False, "error": f"no route {path}"})


def main() -> None:
    config.ensure_dirs()
    print("=" * 64, flush=True)
    print("  Jasper's Trade Bot — history", flush=True)
    print(f"  http://{HOST}:{PORT}/", flush=True)
    print(f"  ledger {_ledger_path()}", flush=True)
    print("=" * 64, flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[hist] shutdown", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
