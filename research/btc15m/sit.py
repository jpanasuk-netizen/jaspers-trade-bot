"""Point the shared research math at the Bitcoin folder.

The rule grid stays in research/eth15m. This file only relocates the
candle cache and the stage files. It does not place orders.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ETH = ROOT.parent / "eth15m"
sys.path.insert(0, str(ETH))

# Hashed at the split lock. Findings are written later and stay out of this list.
DRIVER_FILES = (
    "PROTOCOL.md",
    "sit.py",
    "fetch_split.py",
    "stage.py",
    "run_stage.sh",
    "harness_check.py",
)

import common  # noqa: E402
import strategies  # noqa: E402

common.CACHE = ROOT / "cache"
common.CANDLES = common.CACHE / "candles.csv"
common.MANIFEST = ROOT / "manifest.json"
common.DESIGN_OUT = ROOT / "design_results.json"
common.CONFIRM_OUT = ROOT / "confirm_results.json"
common.SEALED_OUT = ROOT / "sealed_results.json"
common.RUN_LOG = ROOT / "RUN_LOG.md"


def driver_hash() -> str:
    """Hash the Bitcoin driver. Does not include candle files or findings."""
    digest = hashlib.sha256()
    for name in DRIVER_FILES:
        data = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()
