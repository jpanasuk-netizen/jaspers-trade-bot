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
import tkinter  # bundled into the exe; the launch window imports it
import tkinter.ttk  # noqa: F401
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

DESK_VERSION = "2026-09-28"
ROOT = Path(r"\\wsl$\Ubuntu\home\jpanasuk\jev-15m-kalshi-bot")
HUD = "http://127.0.0.1:3000"
HEALTH = HUD + "/api/health"
HISTORY = "http://127.0.0.1:3002"
HISTORY_HEALTH = HISTORY + "/api/health"
DESK_SCRIPT = "/home/jpanasuk/jev-15m-kalshi-bot/scripts/start_desk_wsl.sh"
HISTORY_SCRIPT = "/home/jpanasuk/jev-15m-kalshi-bot/scripts/start_history_wsl.sh"
WINDOWS_PYTHON = r"C:\Users\jpana\AppData\Local\Python\pythoncore-3.14-64\python.exe"
V6_PROXY = ROOT / "scripts" / "localhost_v6_proxy.py"
ENV_PATH = ROOT / ".env"
LIVE_MARK = Path.home() / ".beat15m" / "LIVE_MARK"

# Keep these names live so PyInstaller does not drop the modules.
_BUNDLE = (getpass, msvcrt, tkinter, tkinter.ttk, urllib.error, urllib.request, webbrowser)

# Shown in the launch window and written into .env. First matching line wins
# inside the desk, so every copy of a key is updated together.
KNOBS: list[tuple[str, str, str, str]] = [
    ("ORDER_BUDGET_USD", "Dollars each live order", "2", "Fee included. A full-confidence call spends this. A weaker call spends less."),
    ("ENTRY_CEIL", "Highest ticket price", "0.65", "0.65 means 65 cents. Higher asks are SKIP_PRICEY, including 96¢ favorites."),
    ("ENTRY_FLOOR", "Lowest ticket price", "0.20", "A cheaper ask is the side the book already marked dead."),
    ("CONF_FLOOR", "How sure Jev must be", "0.45", "Below this, the window is skipped."),
    ("STAKE_USD", "Day-stop unit", "2", "Not the live clip. An unset day stop sits down after two of these in losses."),
    ("DAY_STOP_USD", "Stop after this much loss", "1000000", "100000 or more means use two day-stop units instead."),
    ("JEV_TIMEOUT_SEC", "Seconds to wait for Jev", "2.5", "A late answer is skipped."),
    ("EDGE_FLOOR", "Extra edge required", "0", "0 buys Jev's named side. Raise it to demand a clearer gap."),
    ("POLL_SEC", "Seconds between looks", "4", "How often the desk checks the open window."),
    ("MAX_DECISION_LATENCY_MS", "Slow-poke limit (ms)", "4000", "1000 is one second."),
    ("MARTINGALE_TARGET_USD", "Climb-back goal", "6", "Piggy-bank target for the small-ticket climb."),
    ("BASE_STAKE_USD", "Climb-back first ticket", "0.05", "Smallest first step while climbing."),
    ("RETRY_STAKE_USD", "Climb-back retry", "2", "Size of a retry ticket while climbing."),
    ("SIGNAL_QUALITY_MIN", "Messy-game floor", "0.34", "Higher means pickier about a messy window."),
    ("TOXIC_FLOW_MAX", "Mean-flow ceiling", "0.65", "Above this, the window looks like informed flow."),
    ("MAX_VOL_PROXY", "Volatility ceiling", "2.8", "A wilder window is skipped."),
    ("SERIES_TICKER", "Which game", "KXBTC15M", "Bitcoin 15-minute up or down."),
]
TOGGLES: list[tuple[str, str, str]] = [
    ("JEV_ENABLED", "Ask Jev", "1"),
    ("TRADE_ON_LEAN", "Allow a small lean", "0"),
    ("SPIKE_ENABLED", "Spike can fire early", "1"),
    ("MARTINGALE", "Climb-back mode", "1"),
    ("QUANTDINGER_ENABLED", "Ask the chart helper", "1"),
    ("LAYER2_ENABLED", "Slow second model", "0"),
]


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


def _env_first() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in out:
            out[key] = val.strip().strip('"').strip("'")
    return out


def _write_env(updates: dict[str, str]) -> None:
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
    except OSError:
        text = ""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        body = stripped[7:].strip() if stripped.startswith("export ") else stripped
        if stripped and not stripped.startswith("#") and "=" in body:
            key = body.partition("=")[0].strip()
            if key in updates:
                prefix = "export " if stripped.startswith("export ") else ""
                out.append(f"{prefix}{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(raw)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def _set_live(on: bool) -> None:
    LIVE_MARK.parent.mkdir(parents=True, exist_ok=True)
    if on:
        if not LIVE_MARK.is_file():
            LIVE_MARK.write_text("live\n", encoding="utf-8")
    elif LIVE_MARK.is_file():
        LIVE_MARK.unlink()


def _stop_desk() -> None:
    # Bracket the dot so this pgrep does not match its own command line.
    subprocess.run(
        [
            "wsl.exe",
            "-d",
            "Ubuntu",
            "-e",
            "bash",
            "-lc",
            "pids=$(pgrep -f '[.]venv/bin/python -m app.main' || true); "
            "hpids=$(pgrep -f 'python -m app.history_server' || true); "
            "if [ -n \"$pids\" ]; then kill $pids; fi; "
            "if [ -n \"$hpids\" ]; then kill $hpids; fi",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )


def _panic() -> None:
    """Disarm live, write kill files, stop the loop. Does not dump open tickets."""
    for path in (ROOT / "data" / "KILL_SWITCH", Path.home() / ".beat15m" / "KILL_SWITCH"):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("panic\n", encoding="utf-8")
        except OSError:
            pass
    _set_live(False)
    _stop_desk()


def _ask_launch_settings() -> bool:
    """Window of knobs. Cancel leaves the desk alone. Start writes .env."""
    import tkinter as tk
    from tkinter import ttk

    current = _env_first()
    live_on = LIVE_MARK.is_file()
    accepted = {"ok": False}

    root = tk.Tk()
    root.title("Kalshi 15m Desk")
    root.geometry("640x720")
    root.minsize(520, 480)

    head = ttk.Frame(root, padding=(16, 12, 16, 4))
    head.pack(fill="x")
    ttk.Label(head, text="Kalshi 15m Desk", font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(head, text=f"v{DESK_VERSION}  ·  lean off  ·  spike on  ·  cap binds", wraplength=580).pack(anchor="w")
    ttk.Label(
        head,
        text="Pick the clip and the gates. Start saves them and reloads the desk.",
        wraplength=580,
    ).pack(anchor="w", pady=(4, 0))
    status = ttk.Label(head, text="", foreground="#a33")
    status.pack(anchor="w", pady=(6, 0))

    canvas = tk.Canvas(root, highlightthickness=0)
    scroll = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    form = ttk.Frame(canvas, padding=(16, 4, 16, 8))
    form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=form, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    entries: dict[str, tk.StringVar] = {}
    for row, (key, title, default, hint) in enumerate(KNOBS):
        entries[key] = tk.StringVar(value=current.get(key, default))
        ttk.Label(form, text=title, font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Label(form, text=key, foreground="#667").grid(row=row, column=1, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(form, textvariable=entries[key], width=18).grid(row=row, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Label(form, text=hint, wraplength=560, foreground="#445").grid(row=row, column=0, columnspan=3, sticky="w")

    base = len(KNOBS)
    checks: dict[str, tk.BooleanVar] = {}
    for i, (key, title, default) in enumerate(TOGGLES):
        raw = current.get(key, default).strip().lower()
        checks[key] = tk.BooleanVar(value=raw in {"1", "true", "yes", "on"})
        ttk.Checkbutton(form, text=f"{title}  ({key})", variable=checks[key]).grid(
            row=base + i, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )

    live_var = tk.BooleanVar(value=live_on)
    ttk.Checkbutton(form, text="Real money on", variable=live_var).grid(
        row=base + len(TOGGLES), column=0, columnspan=3, sticky="w", pady=(14, 8)
    )

    def _on_mousewheel(event: tk.Event) -> None:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _start() -> None:
        cleaned: dict[str, str] = {}
        for key, _title, _default, _hint in KNOBS:
            val = entries[key].get().strip()
            if key == "SERIES_TICKER":
                if not val:
                    status.configure(text="The game ticker cannot be blank.")
                    return
                cleaned[key] = val
                continue
            try:
                num = float(val)
            except ValueError:
                status.configure(text=f"{key} needs a number.")
                return
            if key == "ORDER_BUDGET_USD" and not (0.5 <= num <= 25):
                status.configure(text="Each live order must be between $0.50 and $25.")
                return
            if key in {"ENTRY_CEIL", "ENTRY_FLOOR"} and not (0.01 <= num <= 0.99):
                status.configure(text=f"{key} must be between 0.01 and 0.99.")
                return
            cleaned[key] = val
        for key, _title, _default in TOGGLES:
            cleaned[key] = "1" if checks[key].get() else "0"
        try:
            _write_env(cleaned)
            _set_live(bool(live_var.get()))
        except OSError as exc:
            status.configure(text=f"Could not save the knobs: {exc}")
            return
        accepted["ok"] = True
        root.destroy()

    bar = ttk.Frame(root, padding=(16, 8, 16, 12))
    bar.pack(fill="x", side="bottom")
    ttk.Button(bar, text="Start desk", command=_start).pack(side="left")
    ttk.Button(bar, text="Open HUD", command=lambda: webbrowser.open(HUD)).pack(side="left", padx=(8, 0))
    ttk.Button(bar, text="Stop", command=_stop_desk).pack(side="left", padx=(8, 0))
    ttk.Button(bar, text="Panic", command=_panic).pack(side="left", padx=(8, 0))
    ttk.Button(bar, text="Cancel", command=root.destroy).pack(side="left", padx=(8, 0))
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    try:
        canvas.unbind_all("<MouseWheel>")
    except Exception:
        pass
    return bool(accepted["ok"])


def _pause() -> None:
    try:
        input("Press Enter to close this window. The desk keeps running.")
    except EOFError:
        pass


def main() -> None:
    os.environ["JASPER_ROOT"] = str(ROOT)
    print("Kalshi 15m Desk", flush=True)
    print(HUD, flush=True)
    if not _ask_launch_settings():
        print("Closed without changing the desk.", flush=True)
        return
    print("Knobs saved.", flush=True)
    sys.path.insert(0, str(ROOT))
    from app.startup_keys import ensure_keys

    ensure_keys()
    if _up(HEALTH):
        print("Reloading the desk so the new knobs load...", flush=True)
        _stop_desk()
        for _ in range(20):
            if not _up(HEALTH):
                break
            time.sleep(0.4)
    if not _up(HEALTH):
        print("Starting the desk on port 3000...", flush=True)
        _spawn(DESK_SCRIPT)
    else:
        print("The desk was already running and did not reload. Close it and start again to load these knobs.", flush=True)
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
            print("Desk stays up if you close this window. Use Stop or Panic in the next launch.", flush=True)
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
