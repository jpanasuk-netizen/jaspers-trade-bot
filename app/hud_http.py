"""HUD HTTP in its own process so the trading loops cannot stall the page."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML_PATH = Path(__file__).with_name("ui.html")
HUD_JSON = Path(__file__).resolve().parent.parent / "data" / "hud.json"


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
            self.send_header("Access-Control-Allow-Origin", "*")
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
        self._send(404, b'{"ok":false}', "application/json")


def serve(host: str = "0.0.0.0", port: int = 3000) -> None:
    HUD_JSON.parent.mkdir(parents=True, exist_ok=True)
    httpd = Server((host, port), Handler)
    print(f"[hud-http] {host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
