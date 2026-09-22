"""Easy knobs GUI on :3004. Reads/writes .env. No secret values returned."""
from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import ROOT, config
from .spin import live_armed

HTML_PATH = Path(__file__).with_name("settings.html")
PORT = int(os.environ.get("SETTINGS_PORT", "3004"))
HOST = os.environ.get("SETTINGS_HOST", "0.0.0.0")
ENV_PATH = ROOT / ".env"
SECRET_KEYS = {
    "TYPESAFE_API_KEY",
    "TWITTER_API_KEY",
    "TWITTER_BEARER_TOKEN",
    "TWITTER_CONSUMER_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
    "KALSHI_API_KEY_ID",
    "NVIDIA_API_KEY",
}


def _parse_env(text: str) -> list[tuple[str, str | None]]:
    rows: list[tuple[str, str | None]] = []
    for raw in text.splitlines():
        if "=" in raw and not raw.strip().startswith("#") and raw.strip():
            k, _, v = raw.partition("=")
            rows.append((k.strip(), v))
        else:
            rows.append(("", raw))
    return rows


def _read_env_map() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.is_file():
        return out
    for k, v in _parse_env(ENV_PATH.read_text(encoding="utf-8")):
        if k:
            out[k] = v.strip().strip('"').strip("'") if v is not None else ""
    return out


def _write_env(updates: dict[str, str]) -> None:
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    rows = _parse_env(text)
    seen: set[str] = set()
    lines: list[str] = []
    for k, v in rows:
        if not k:
            lines.append(v if v is not None else "")
            continue
        if k in updates:
            lines.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            lines.append(f"{k}={v}")
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _live_path() -> Path:
    return Path(config.live_mark)


def _set_live(on: bool) -> None:
    p = _live_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if on:
        p.write_text("live\n", encoding="utf-8")
    elif p.is_file():
        p.unlink()


def _restart_desk() -> str:
    script = r"""
set -e
pids=$(pgrep -f '[.]venv/bin/python -m app.main' || true)
if [ -n "$pids" ]; then
  kill $pids || true
  sleep 1
fi
cd /home/jpanasuk/jev-15m-kalshi-bot
nohup .venv/bin/python -m app.main >> data/logs/desk.out 2>&1 &
echo restarted
"""
    r = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return (r.stdout or r.stderr or "").strip()[:400]


def _payload() -> dict[str, Any]:
    env = _read_env_map()
    public = {k: v for k, v in env.items() if k not in SECRET_KEYS}
    cash = None
    try:
        from . import martingale as mg

        cash = mg.kalshi_cash()
    except Exception:  # noqa: BLE001
        cash = None
    return {
        "ok": True,
        "live": live_armed(),
        "cash": cash,
        "typesafe_set": bool(env.get("TYPESAFE_API_KEY") or config.typesafe_api_key),
        "env": public,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print("[settings]", fmt % args, flush=True)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/settings":
            self._send(200, json.dumps(_payload()).encode(), "application/json")
            return
        self._send(404, b"nope", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode() or "{}")
        except Exception:  # noqa: BLE001
            self._send(400, b'{"ok":false,"error":"bad json"}', "application/json")
            return
        if path == "/api/settings":
            updates = data.get("env") or {}
            clean: dict[str, str] = {}
            for k, v in updates.items():
                k = str(k).strip()
                if not k or k in SECRET_KEYS:
                    continue
                if not k.replace("_", "").isalnum():
                    continue
                clean[k] = str(v).strip()
            _write_env(clean)
            msg = "saved"
            if data.get("restart"):
                msg = _restart_desk() or "restarted"
            self._send(200, json.dumps({"ok": True, "msg": msg}).encode(), "application/json")
            return
        if path == "/api/live":
            _set_live(bool(data.get("on")))
            self._send(200, json.dumps({"ok": True, "live": live_armed()}).encode(), "application/json")
            return
        self._send(404, b"nope", "text/plain")


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[settings] http://127.0.0.1:{PORT}/", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
