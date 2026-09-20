#!/usr/bin/env python3
"""Start HUD in a thread, hit APIs, print results, exit."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import Handler  # noqa: E402
from app import state  # noqa: E402
from app.config import config  # noqa: E402


def get(path: str) -> dict:
    url = f"http://127.0.0.1:{config.port}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read().decode()
    if path.endswith(".html") or path in {"/", "/hud"} or path.startswith("/index"):
        return {"html_len": len(raw), "has_title": "15-min BTC JAP" in raw, "has_yes": "YES" in raw}
    return json.loads(raw)


def main() -> int:
    config.ensure_dirs()
    server = ThreadingHTTPServer((config.host, config.port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.4)
    print("serving on", config.port)
    state.tick(do_spin=True)
    hud = get("/")
    health = get("/api/health")
    st = get("/api/state")
    print("HUD", json.dumps(hud))
    print("HEALTH", json.dumps(health))
    latest = st.get("latest") or {}
    print("STATE", json.dumps({
        "connection": st.get("connection"),
        "ticker": (latest.get("window") or {}).get("ticker"),
        "spot": (latest.get("spot") or {}).get("price"),
        "side": (latest.get("decision") or {}).get("kalshi_side"),
        "conf": (latest.get("decision") or {}).get("conf"),
        "yes_ask": (latest.get("window") or {}).get("yes_ask"),
        "no_ask": (latest.get("window") or {}).get("no_ask"),
        "mode": (st.get("meta") or {}).get("dryRun"),
        "last_spin": (st.get("last_spin") or {}).get("result"),
    }, indent=2))
    spin = get("/api/tape")
    print("TAPE_LEN", len(spin.get("tape") or []))
    server.shutdown()
    print("SERVER_TEST_OK")
    return 0 if hud.get("has_title") and health.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
