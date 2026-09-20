"""Jev-X → 15-min Kalshi BTC YES/NO bot. Trading-blocks HUD on :3000."""
from __future__ import annotations

import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import state
from .config import config
from .judge import judge
from .sentiment import get_sentiment
from .spin import evaluate_spin, history_records, history_stats, live_armed, recent_tape

HTML_PATH = Path(__file__).with_name("ui.html")
HISTORY_PATH = Path(__file__).with_name("history.html")


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    try:
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        return


def _html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class DeskServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


class Handler(BaseHTTPRequestHandler):
    server_version = "Jev15mKalshi/1.0"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # access log was filling the pipe and stalling every request

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        try:
            if path in {"/", "/index.html", "/hud", "/trading"}:
                html = HTML_PATH.read_text(encoding="utf-8") if HTML_PATH.is_file() else "<h1>missing ui.html</h1>"
                _html_response(self, html)
                return
            if path in {"/history", "/history.html"}:
                html = HISTORY_PATH.read_text(encoding="utf-8") if HISTORY_PATH.is_file() else "<h1>missing history.html</h1>"
                _html_response(self, html)
                return
            if path == "/api/state":
                _json_response(self, 200, state.current())
                return
            if path == "/api/judgment":
                force = (qs.get("force") or ["0"])[0] in {"1", "true", "yes"}
                _json_response(self, 200, judge(force=force))
                return
            if path == "/api/sentiment":
                force = (qs.get("force") or ["0"])[0] in {"1", "true", "yes"}
                _json_response(self, 200, get_sentiment("BTC", force=force))
                return
            if path == "/api/tape":
                _json_response(self, 200, {"ok": True, "tape": recent_tape(40)})
                return
            if path == "/api/quant":
                from .quant import desk_quant_snapshot

                _json_response(self, 200, desk_quant_snapshot())
                return
            if path == "/api/quantdinger":
                from .quantdinger import btc_research_pack

                _json_response(self, 200, btc_research_pack(force=True))
                return
            if path == "/api/charts":
                from .chart_data import chart_series

                _json_response(self, 200, chart_series())
                return
            if path == "/api/btcc":
                from .btcc_knowledge import DOCTRINE, btcc_signal_board

                board = btcc_signal_board(force=True)
                board["doctrine_full"] = DOCTRINE
                _json_response(self, 200, board)
                return
            if path == "/api/history":
                try:
                    limit = int((qs.get("limit") or ["250"])[0])
                except (TypeError, ValueError):
                    limit = 250
                rows = history_records(max(1, min(limit, 2000)))
                _json_response(self, 200, {
                    "ok": True,
                    "liveArmed": live_armed(),
                    "rows": rows,
                    "stats": history_stats(rows),
                })
                return
            if path == "/api/health":
                _json_response(self, 200, {
                    "ok": True,
                    "name": "Jasper's Trade Bot",
                    "port": config.port,
                    "series": config.series_ticker,
                    "liveArmed": live_armed(),
                    "typesafe": bool(config.typesafe_api_key),
                    "twitter": bool(config.twitter_api_key),
                })
                return
            _json_response(self, 404, {"ok": False, "error": f"no route {path}"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:  # noqa: BLE001
            _json_response(self, 500, {"ok": False, "error": str(exc)[:200]})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            payload = {}

        try:
            if path == "/api/tick":
                do_spin = bool(payload.get("spin", True))
                _json_response(self, 200, state.tick(do_spin=do_spin))
                return
            if path == "/api/spin":
                rec = evaluate_spin(force_judge=bool(payload.get("force", True)))
                state.tick(do_spin=False)
                _json_response(self, 200, {"ok": True, "spin": rec, "state": state.current()})
                return
            if path == "/api/judgment":
                _json_response(self, 200, judge(force=True))
                return
            _json_response(self, 404, {"ok": False, "error": f"no route {path}"})
        except Exception as exc:  # noqa: BLE001
            _json_response(self, 500, {"ok": False, "error": str(exc)})


def _wsl_ip() -> str:
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def _loop() -> None:
    """Legacy fallback loop — production uses app.runtime."""
    print(f"[loop] desk poll every {config.poll_sec:.0f}s  stake=${config.stake_usd:.2f}  "
          f"conf>={config.conf_floor}  entry<={config.entry_ceil}", flush=True)
    while True:
        try:
            state.tick(do_spin=True)
            conn = state.current().get("connection")
            err = state.current().get("error")
            mode = "LIVE" if live_armed() else "PAPER"
            print(f"[loop] tick ok mode={mode} conn={conn} err={err}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[loop] tick error: {exc}", flush=True)
        time.sleep(max(5.0, config.poll_sec))


def main() -> None:
    from . import runtime

    config.ensure_dirs()
    print("=" * 64, flush=True)
    print("  Jasper's Trade Bot — production desk", flush=True)
    print(f"  HUD   http://{config.host}:{config.port}/", flush=True)
    print(f"  Keys  typesafe={bool(config.typesafe_api_key)}  qd={config.quantdinger_base_url}", flush=True)
    print("=" * 64, flush=True)
    from multiprocessing import Process

    from .hud_http import serve as serve_hud

    http_proc = Process(
        target=serve_hud,
        kwargs={"host": "0.0.0.0", "port": int(config.port)},
        name="hud-http",
        daemon=True,
    )
    http_proc.start()
    print(f"  HTTP  http://127.0.0.1:{config.port}/  (WSL {_wsl_ip()}:{config.port})", flush=True)
    mode = "LIVE" if live_armed() else "PAPER"
    print(f"  MODE  {mode}   series={config.series_ticker}   stake=${config.stake_usd:.2f}", flush=True)
    print(f"  Gates conf>={config.conf_floor}  entry<={config.entry_ceil}  lean={config.trade_on_lean}", flush=True)
    print(f"  Keys  typesafe={bool(config.typesafe_api_key)}  twitter={bool(config.twitter_api_key)}", flush=True)
    print(f"  Arm   echo live > {config.live_mark}   (kill: delete the file)", flush=True)
    print("=" * 64, flush=True)
    runtime.warmup()
    runtime.start_background()
    try:
        while http_proc.is_alive():
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[main] shutdown", flush=True)
    finally:
        if http_proc.is_alive():
            http_proc.terminate()


if __name__ == "__main__":
    main()
