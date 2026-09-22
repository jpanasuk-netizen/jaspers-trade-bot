"""Publish the history-desk win/loss summary for the public page.

Same numbers as http://127.0.0.1:3002. No cash, no keys, no order ids.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import config

_PUSH_AT = 0.0


def _ledger_rows() -> list[dict[str, Any]]:
    path = config.data_dir / "spin_ledger.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_record() -> dict[str, Any]:
    from .settle import attach_outcome

    sb_path = config.data_dir / "scoreboard.json"
    sb: dict[str, Any] = {}
    if sb_path.is_file():
        try:
            sb = json.loads(sb_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sb = {}
    recent: list[dict[str, Any]] = []
    for rec in _ledger_rows():
        if str(rec.get("result") or "") != "LIVE_FILLED" or not rec.get("filled"):
            continue
        settled = attach_outcome(rec)
        won = settled.get("won")
        recent.append(
            {
                "ts": rec.get("ts"),
                "side": rec.get("side"),
                "entry": rec.get("entry"),
                "won": won,
            }
        )
    recent = recent[-8:]
    recent.reverse()
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "wins": int(sb.get("wins") or 0),
        "losses": int(sb.get("losses") or 0),
        "pushes": int(sb.get("pushes") or 0),
        "pnl_usd": sb.get("pnlUsd") or 0,
        "fills": int(sb.get("fills") or 0),
        "last_side": sb.get("lastSide"),
        "last_result": sb.get("lastResult"),
        "recent": recent,
        "source": "history desk",
    }


def _push(path: Path) -> None:
    global _PUSH_AT
    now = time.time()
    if now - _PUSH_AT < 180:
        return
    repo = path.resolve().parents[1]
    commit = repo / "scripts" / "_public_commit.txt"
    commit.write_text(
        "Update the public win/loss record.\n\nSame summary the history desk shows. No keys.\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(["git", "add", "docs/record.json"], cwd=repo, check=True, capture_output=True)
        status = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo)
        if status.returncode == 0:
            return
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Jeremy Panasuk",
                "-c",
                "user.email=jpanasuk@gmail.com",
                "commit",
                "-F",
                str(commit),
            ],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "HEAD"], cwd=repo, check=True, capture_output=True)
        _PUSH_AT = now
    except (subprocess.CalledProcessError, OSError):
        return
    finally:
        commit.unlink(missing_ok=True)


def publish_record() -> None:
    record = build_record()
    path = Path(__file__).resolve().parents[1] / "docs" / "record.json"
    text = json.dumps(record, indent=2) + "\n"
    previous = path.read_text(encoding="utf-8") if path.is_file() else ""
    # Ignore updated_at when deciding if the numbers changed.
    def core(raw: str) -> str:
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return raw
        data.pop("updated_at", None)
        return json.dumps(data, sort_keys=True)

    path.write_text(text, encoding="utf-8")
    if core(previous) != core(text):
        _push(path)
