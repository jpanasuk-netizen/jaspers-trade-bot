"""Windows entry for Kalshi 15m Desk.exe.

Asks only when a key is missing, saves it in the WSL repo .env, then starts
the desk and opens the HUD. The desk process is detached so closing this
window does not take it down.
"""
from __future__ import annotations

import getpass  # collected into the frozen exe; startup_keys imports it at runtime
import msvcrt  # Windows getpass reads the console through this module
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(r"\\wsl$\Ubuntu\home\jpanasuk\jev-15m-kalshi-bot")
HUD = "http://127.0.0.1:3000"
HEALTH = HUD + "/api/health"
HISTORY = "http://127.0.0.1:3002"
HISTORY_HEALTH = HISTORY + "/api/health"
DESK_SCRIPT = "/home/jpanasuk/jev-15m-kalshi-bot/scripts/start_desk_wsl.sh"
HISTORY_SCRIPT = "/home/jpanasuk/jev-15m-kalshi-bot/scripts/start_history_wsl.sh"
WINDOWS_PYTHON = r"C:\Users\jpana\AppData\Local\Python\pythoncore-3.14-64\python.exe"
V6_PROXY = ROOT / "scripts" / "localhost_v6_proxy.py"

# Keep these names live so PyInstaller does not drop the modules.
_BUNDLE = (getpass, msvcrt, urllib.error, urllib.request, webbrowser)


def _box(text: str, flags: int = 0x40) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, "Kalshi 15m Desk", flags)
    except Exception:
        pass


def _up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _spawn_windows(cmd: list[str]) -> None:
    kwargs = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        subprocess.Popen(cmd, creationflags=flags, **kwargs)


def _spawn(script: str) -> None:
    # wsl.exe has to stay the parent of python. A trailing '&' lets bash
    # exit, and WSL then tears the server down with that session.
    cmd = ["wsl.exe", "-d", "Ubuntu", "-e", "bash", script]
    kwargs = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError:
        subprocess.Popen(cmd, creationflags=flags, **kwargs)


def _log_tail(name: str = "desk.out") -> str:
    log = ROOT / "data" / "logs" / name
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    except Exception as exc:
        return f"(could not read the log: {exc})"
    return "\n".join(lines)


def _pause() -> None:
    try:
        input("Press Enter to close this window. The desk keeps running.")
    except EOFError:
        pass


def main() -> None:
    os.environ["JASPER_ROOT"] = str(ROOT)
    print("Kalshi 15m Desk", flush=True)
    print(HUD, flush=True)
    sys.path.insert(0, str(ROOT))
    from app.startup_keys import ensure_keys

    ensure_keys()
    if not _up(HEALTH):
        print("Starting the desk on port 3000...", flush=True)
        _spawn(DESK_SCRIPT)
    else:
        print("Desk is already running.", flush=True)
    if not _up(HISTORY_HEALTH):
        print("Starting history on port 3002...", flush=True)
        _spawn(HISTORY_SCRIPT)
    else:
        print("History is already running.", flush=True)
    if not (_up("http://[::1]:3000/api/health") and _up("http://[::1]:3002/api/health")):
        print("Opening localhost for the browser...", flush=True)
        _spawn_windows([WINDOWS_PYTHON, str(V6_PROXY)])
    for _ in range(40):
        desk_up = _up(HEALTH)
        history_up = _up(HISTORY_HEALTH)
        if desk_up and history_up:
            print(f"Desk is up. Opening {HUD}", flush=True)
            print(f"History is up at {HISTORY}", flush=True)
            webbrowser.open(HUD)
            _pause()
            return
        time.sleep(1)
    if not _up(HEALTH):
        print("The desk did not answer on port 3000.", flush=True)
        print(_log_tail(), flush=True)
        _box("The Kalshi desk did not start. Leave the black window open and read the last lines.", 0x10)
    else:
        print("History did not answer on port 3002.", flush=True)
        print(_log_tail("history.out"), flush=True)
        _box("The desk is up, but history on port 3002 did not start.", 0x10)
    _pause()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        _box("Kalshi 15m Desk failed before it could start. The black window has the error.", 0x10)
        try:
            input("Press Enter to close this window.")
        except EOFError:
            pass
        raise SystemExit(1)
