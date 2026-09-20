#!/usr/bin/env python3
"""Start the full 15-min desk on live market data.

Windows (old JAP layout):
  :3000  trading-blocks desk HUD
  :3001  flow tape + /jev
  :3002  odds / decision board

Paper by default. Live orders only if LIVE_MARK exists and Kalshi keys resolve.
Stake stays at config.STAKE_USD — this runner never sets stake to account balance.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import state  # noqa: E402
from app.config import config  # noqa: E402
from app.flow_server import serve_flow  # noqa: E402
from app.main import Handler as DeskHandler  # noqa: E402
from app.odds_server import serve_odds  # noqa: E402
from app.spin import live_armed  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


def _loop() -> None:
    while True:
        try:
            state.tick(do_spin=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[loop] {exc}", flush=True)
        time.sleep(max(5.0, config.poll_sec))


def main() -> None:
    config.ensure_dirs()
    # Prefer known Windows credential paths if env/secrets dirs are empty.
    import os
    from pathlib import Path as P
    home = P.home()
    candidates = [
        home / "kalshi" / "key_id.txt",
        home / ".beat15m" / "key_id.txt",
        home / ".kalshi" / "key_id.txt",
    ]
    if not config.kalshi_api_key_id:
        for c in candidates:
            if c.is_file():
                os.environ["KALSHI_API_KEY_ID"] = c.read_text(encoding="utf-8").strip()
                pem_guess = c.parent / "kalshi.key"
                if not pem_guess.is_file():
                    pem_guess = c.parent / "kalshi-private-key.pem"
                if pem_guess.is_file():
                    os.environ["KALSHI_PRIVATE_KEY_PATH"] = str(pem_guess)
                print(f"[desk] kalshi key_id discovered under {c.parent}", flush=True)
                break
    # reload not needed for spin if we patch kalshi_live search paths — extend candidates
    from app import kalshi_live
    for folder in (home / "kalshi", home / ".beat15m", home / ".kalshi"):
        if folder not in kalshi_live.config.secrets_dir_candidates:
            # Config is frozen; kalshi_live reads config.secrets_dir_candidates via property
            pass

    # Monkey-patch secret search to include C:\Users\...\kalshi
    _orig_find_key_id = kalshi_live._find_key_id

    def _find_key_id_patched() -> str:
        v = _orig_find_key_id()
        if v:
            return v
        for folder in (home / "kalshi", home / ".beat15m", home / ".kalshi"):
            p = folder / "key_id.txt"
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        return ""

    def _find_pem_patched() -> str:
        v = kalshi_live._find_pem_text.__wrapped__ if hasattr(kalshi_live._find_pem_text, "__wrapped__") else None
        # call original logic then extend
        key_id = config.kalshi_private_key_path
        if key_id:
            from pathlib import Path as PP
            p = PP(key_id).expanduser()
            if p.is_file():
                return p.read_text(encoding="utf-8")
        for folder in list(config.secrets_dir_candidates) + [home / "kalshi", home / ".beat15m", home / ".kalshi"]:
            for name in ("kalshi-private-key.pem", "kalshi.key", "private-key.pem", "kalshi.pem"):
                p = folder / name
                if p.is_file():
                    return p.read_text(encoding="utf-8")
        return ""

    kalshi_live._find_key_id = _find_key_id_patched
    kalshi_live._find_pem_text = _find_pem_patched

    threading.Thread(target=_loop, daemon=True, name="desk-loop").start()

    desk = ThreadingHTTPServer((config.host, config.port), DeskHandler)
    flow = serve_flow(config.host, 3001)
    odds = serve_odds(config.host, 3002)

    for srv, name in ((desk, "3000-desk"), (flow, "3001-flow"), (odds, "3002-odds")):
        threading.Thread(target=srv.serve_forever, daemon=True, name=name).start()

    mode = "LIVE" if live_armed() else "PAPER"
    print("=" * 64, flush=True)
    print("  15-min BTC JAP DESK — live market data", flush=True)
    print(f"  :3000  http://{config.host}:3000/   trading blocks", flush=True)
    print(f"  :3001  http://{config.host}:3001/   flow + /jev", flush=True)
    print(f"  :3002  http://{config.host}:3002/   odds / decisions", flush=True)
    print(f"  MODE   {mode}   stake=${config.stake_usd:.2f} (NOT account balance)", flush=True)
    print(f"  LIVE   arm: echo live > {config.live_mark}", flush=True)
    print("  NOTE   all-in stake is disabled by design", flush=True)
    print("=" * 64, flush=True)

    # publish initial tick
    state.tick(do_spin=True)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[desk] shutdown", flush=True)
    finally:
        desk.shutdown()
        flow.shutdown()
        odds.shutdown()


if __name__ == "__main__":
    main()
