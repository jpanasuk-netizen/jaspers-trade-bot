"""Windows entry for Kalshi 15m Desk.exe.

Asks for any missing keys, saves them in the WSL repo .env, then starts the desk.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"\\wsl$\Ubuntu\home\jpanasuk\jev-15m-kalshi-bot")


def main() -> None:
    os.environ["JASPER_ROOT"] = str(ROOT)
    os.environ["JASPER_FORCE_PROMPT"] = "1"
    sys.path.insert(0, str(ROOT))
    from app.startup_keys import ensure_keys

    ensure_keys()
    print("Starting the desk at http://127.0.0.1:3000", flush=True)
    subprocess.Popen(
        [
            "wsl",
            "-d",
            "Ubuntu",
            "-e",
            "bash",
            "-lc",
            "cd /home/jpanasuk/jev-15m-kalshi-bot && JASPER_NO_PROMPT=1 nohup .venv/bin/python -m app.main >> data/logs/desk.out 2>&1 &",
        ]
    )
    try:
        input("Desk is starting. Press Enter to close this window.")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
