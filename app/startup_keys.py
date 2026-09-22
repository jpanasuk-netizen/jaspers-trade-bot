"""Ask for the keys the desk cannot run without, then save them in .env.

Headless starts (the already-running desk) do not prompt. A console or the
desktop exe does, and only for keys that are missing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

def _root() -> Path:
    override = os.environ.get("JASPER_ROOT", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1]

# Secrets are typed with no echo. The PEM is a path, not the key text.
REQUIRED = (
    ("TYPESAFE_API_KEY", "TypeSafe Jev API key", True),
    ("KALSHI_API_KEY_ID", "Kalshi API key id", True),
    ("KALSHI_PRIVATE_KEY_PATH", "Full path to the Kalshi private key file", False),
)


def _should_prompt() -> bool:
    if os.environ.get("JASPER_NO_PROMPT", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("JASPER_FORCE_PROMPT", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if getattr(sys, "frozen", False):
        return True
    try:
        return bool(sys.stdin.isatty())
    except Exception:  # noqa: BLE001
        return False


def _read_env(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, _, val = line.partition("=")
        found[key.strip()] = val.strip().strip('"').strip("'")
    return found


def _write_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        if "=" in raw and not raw.strip().startswith("#"):
            key = raw.split("=", 1)[0].strip()
            if key.startswith("export "):
                key = key[7:].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(raw)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _current(name: str, saved: dict[str, str]) -> str:
    return (os.environ.get(name) or saved.get(name) or "").strip()


def _usable(name: str, value: str) -> bool:
    if not value:
        return False
    if name == "KALSHI_PRIVATE_KEY_PATH":
        return Path(value).expanduser().is_file()
    return True


def ensure_keys() -> None:
    if not _should_prompt():
        return
    env_path = _root() / ".env"
    saved = _read_env(env_path)
    updates: dict[str, str] = {}
    print("", flush=True)
    print("Jasper desk needs three keys. Press Enter to keep one that is already saved.", flush=True)
    for name, label, secret in REQUIRED:
        have = _current(name, saved)
        ok = _usable(name, have)
        while True:
            hint = " [saved]" if ok else " [required]"
            prompt = f"{label}{hint}: "
            try:
                if secret:
                    import getpass

                    typed = getpass.getpass(prompt)
                else:
                    typed = input(prompt)
            except EOFError:
                print("No console input. Starting with the keys already saved.", flush=True)
                return
            typed = typed.strip().strip('"').strip("'")
            if not typed and ok:
                break
            if not typed:
                print(f"  {name} is still missing.", flush=True)
                continue
            if name == "KALSHI_PRIVATE_KEY_PATH" and not Path(typed).expanduser().is_file():
                print("  That file was not found. Paste the full path to the .pem.", flush=True)
                continue
            updates[name] = typed
            os.environ[name] = typed
            ok = True
            break
    if updates:
        _write_env(env_path, updates)
        print("Saved the new keys to .env", flush=True)
    else:
        print("Using the saved keys.", flush=True)
