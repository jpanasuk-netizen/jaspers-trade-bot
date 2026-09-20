#!/usr/bin/env python3
"""Entry point: python run.py  → HUD on http://127.0.0.1:3000/"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
