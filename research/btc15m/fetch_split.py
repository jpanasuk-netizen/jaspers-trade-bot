"""Download BTCUSDT 15m candles and lock the sealed third.

Prints counts, timestamps, and hashes. Does not print prices and does not score rules.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sit  # noqa: F401  rebinds the shared paths onto this folder

from common import (  # noqa: E402
    BAR_MS,
    BREAKEVEN,
    CACHE,
    CANDLES,
    FEE,
    KELLY_CAP,
    KELLY_HALF,
    MANIFEST,
    MAX_MISSING_FRAC,
    MIN_BARS,
    MIN_CAL_N,
    MIN_TRADES,
    PAYOUT,
    RUN_LOG,
    WIN_MIN,
    append_log,
    refuse_if,
    slice_bounds,
    source_hash,
    write_json,
)
from strategies import SPEC_LIST, build_specs  # noqa: E402

UA = "btc15m-research/1.0"
VISION = "https://data.binance.vision/data/spot"
SYMBOL = "BTCUSDT"
DESIGN_OUT = Path(__file__).resolve().parent / "design_results.json"


def _request(url: str) -> bytes | None:
    delay = 1.0
    for attempt in range(4):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == 3 or exc.code not in (429, 500, 502, 503, 504):
                raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(delay)
        delay *= 2
    return None


def _download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    payload = _request(url)
    if payload is None:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return True


def _verify(zip_url: str, dest: Path) -> None:
    text = _request(zip_url + ".CHECKSUM")
    if text is None:
        print(f"checksum missing {dest.name}", flush=True)
        return
    token = text.decode("utf-8", errors="replace").strip().split()[0]
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if token != digest:
        dest.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch for {dest.name}")


def _norm_time(raw: int) -> int:
    if raw > 100_000_000_000_000:
        return raw // 1000
    return raw


def _parse_zip(dest: Path) -> list[tuple[int, float, float, float, float, float]]:
    rows: list[tuple[int, float, float, float, float, float]] = []
    with zipfile.ZipFile(dest) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise SystemExit(f"unexpected zip layout {dest.name}")
        text = archive.read(names[0]).decode("utf-8")
    for line in text.splitlines():
        if not line or line[0].isalpha():
            continue
        parts = line.split(",")
        if len(parts) < 6:
            continue
        rows.append(
            (
                _norm_time(int(float(parts[0]))),
                float(parts[1]),
                float(parts[2]),
                float(parts[3]),
                float(parts[4]),
                float(parts[5]),
            )
        )
    return rows


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[str]:
    year, month = start
    out = []
    while (year, month) <= end:
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return out


def _vision_rows() -> list[tuple[int, float, float, float, float, float]]:
    now = datetime.now(timezone.utc)
    if now.month == 1:
        last_full = (now.year - 1, 12)
    else:
        last_full = (now.year, now.month - 1)
    rows: list[tuple[int, float, float, float, float, float]] = []
    started = False
    zips = CACHE / "zips"
    for ym in _months((2017, 8), last_full):
        name = f"{SYMBOL}-15m-{ym}.zip"
        url = f"{VISION}/monthly/klines/{SYMBOL}/15m/{name}"
        dest = zips / name
        if not _download(url, dest):
            if not started:
                print(f"vision leading miss {ym}", flush=True)
                continue
            raise SystemExit(f"vision gap at {ym}")
        _verify(url, dest)
        started = True
        rows.extend(_parse_zip(dest))
        print(f"vision {ym} rows={len(rows)}", flush=True)
    if not started:
        raise urllib.error.URLError("no monthly BTCUSDT 15m files")
    yesterday = (now - timedelta(days=1)).date()
    day = datetime(now.year, now.month, 1, tzinfo=timezone.utc).date()
    while day <= yesterday:
        ymd = day.isoformat()
        name = f"{SYMBOL}-15m-{ymd}.zip"
        url = f"{VISION}/daily/klines/{SYMBOL}/15m/{name}"
        dest = zips / name
        if not _download(url, dest):
            if (yesterday - day).days <= 2:
                print(f"vision daily tail miss {ymd}", flush=True)
                break
            raise SystemExit(f"vision daily miss {ymd}")
        _verify(url, dest)
        rows.extend(_parse_zip(dest))
        print(f"vision {ymd} rows={len(rows)}", flush=True)
        day += timedelta(days=1)
    return rows


def _rest_rows() -> list[tuple[int, float, float, float, float, float]]:
    rows: list[tuple[int, float, float, float, float, float]] = []
    start = 1_502_928_000_000
    now_ms = int(time.time() * 1000)
    while True:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={SYMBOL}&interval=15m&limit=1000&startTime={start}"
        )
        payload = _request(url)
        if not payload:
            break
        batch = json.loads(payload.decode("utf-8"))
        if not batch:
            break
        for item in batch:
            opened_ms = _norm_time(int(item[0]))
            if opened_ms + BAR_MS > now_ms - 60_000:
                continue
            rows.append(
                (
                    opened_ms,
                    float(item[1]),
                    float(item[2]),
                    float(item[3]),
                    float(item[4]),
                    float(item[5]),
                )
            )
        last = _norm_time(int(batch[-1][0]))
        nxt = last + BAR_MS
        print(f"rest rows={len(rows)}", flush=True)
        if nxt <= start or len(batch) < 1000:
            break
        start = nxt
        time.sleep(0.05)
    return rows


def _clean(rows: list[tuple[int, float, float, float, float, float]]):
    now_ms = int(time.time() * 1000)
    closed = [row for row in rows if row[0] + BAR_MS <= now_ms - 60_000]
    by = {}
    for row in closed:
        by[row[0]] = row
    return [by[key] for key in sorted(by)]


def _gaps(rows) -> dict[str, int]:
    gaps = missing = max_gap = 0
    for prev, nxt in zip(rows, rows[1:]):
        delta = nxt[0] - prev[0]
        if delta != BAR_MS:
            gaps += 1
            if delta > max_gap:
                max_gap = delta
            if delta > BAR_MS:
                missing += delta // BAR_MS - 1
    return {"gap_events": gaps, "missing_bars": missing, "max_gap_ms": max_gap}


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(rows) -> list[str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{ot},{o:.8f},{h:.8f},{l:.8f},{c:.8f},{v:.8f}\n"
        for ot, o, h, l, c, v in rows
    ]
    with CANDLES.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("open_time_ms,open,high,low,close,volume\n")
        handle.writelines(lines)
    return lines


def _hash_lines(lines: list[str], start: int, end: int) -> str:
    digest = hashlib.sha256()
    for line in lines[start:end]:
        digest.update(line.encode())
    return digest.hexdigest()


def main() -> None:
    refuse_if(DESIGN_OUT, "design results already exist; refusing to rebuild the split")
    try:
        rows = _clean(_vision_rows())
        source = "binance-vision-spot"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"vision failed {type(exc).__name__}; trying rest", flush=True)
        rows = []
        source = ""
    if len(rows) < MIN_BARS:
        print(f"vision rows={len(rows)} below minimum; trying rest", flush=True)
        rows = _clean(_rest_rows())
        source = "binance-rest-spot"
    if len(rows) < MIN_BARS:
        raise SystemExit(f"only {len(rows)} closed bars; need {MIN_BARS}")
    gap = _gaps(rows)
    missing_frac = gap["missing_bars"] / (len(rows) + gap["missing_bars"])
    if missing_frac > MAX_MISSING_FRAC:
        raise SystemExit(f"too many missing bars {gap}")
    lines = _write(rows)
    bounds = slice_bounds(len(rows))
    build_specs()
    names = [str(spec["name"]) for spec in SPEC_LIST]
    hashes = {
        "file": hashlib.sha256(CANDLES.read_bytes()).hexdigest(),
        "design": _hash_lines(lines, bounds["design"][0], bounds["design"][1]),
        "confirm": _hash_lines(lines, bounds["confirm"][0], bounds["confirm"][1]),
        "sealed": _hash_lines(lines, bounds["sealed"][0], bounds["sealed"][1]),
    }
    manifest = {
        "symbol": SYMBOL,
        "interval": "15m",
        "source": source,
        "payout": PAYOUT,
        "fee": FEE,
        "breakeven_win_rate": BREAKEVEN,
        "win_min": WIN_MIN,
        "min_trades": MIN_TRADES,
        "kelly_half": KELLY_HALF,
        "kelly_cap": KELLY_CAP,
        "min_calendar_n": MIN_CAL_N,
        "n": len(rows),
        "bounds": bounds,
        "times": {
            "first": _iso(rows[0][0]),
            "last": _iso(rows[-1][0]),
            "design_first": _iso(rows[bounds["design"][0]][0]),
            "design_last": _iso(rows[bounds["design"][1] - 1][0]),
            "confirm_first": _iso(rows[bounds["confirm"][0]][0]),
            "confirm_last": _iso(rows[bounds["confirm"][1] - 1][0]),
            "sealed_first": _iso(rows[bounds["sealed"][0]][0]),
            "sealed_last": _iso(rows[-1][0]),
        },
        "gaps": gap,
        "missing_frac": missing_frac,
        "hashes": hashes,
        "source_hash": source_hash(),
        "driver_hash": sit.driver_hash(),
        "strategy_names": names,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Bitcoin study. Sealed rows are hidden. Do not score the full grid on them.",
    }
    write_json(MANIFEST, manifest)
    if not RUN_LOG.exists():
        append_log("# BTC 15m research run log\n")
    append_log(
        "\n## Split locked\n\n"
        f"- symbol: {SYMBOL}\n"
        f"- source: {source}\n"
        f"- bars: {len(rows)}\n"
        f"- first: {manifest['times']['first']}\n"
        f"- last: {manifest['times']['last']}\n"
        f"- design rows: {bounds['design'][1] - bounds['design'][0]} "
        f"({manifest['times']['design_first']} to {manifest['times']['design_last']})\n"
        f"- confirm rows: {bounds['confirm'][1] - bounds['confirm'][0]} "
        f"({manifest['times']['confirm_first']} to {manifest['times']['confirm_last']})\n"
        f"- sealed rows: {bounds['sealed'][1] - bounds['sealed'][0]} "
        f"({manifest['times']['sealed_first']} to {manifest['times']['sealed_last']})\n"
        f"- gaps: {gap}\n"
        f"- file sha256: {hashes['file']}\n"
        f"- sealed sha256: {hashes['sealed']}\n"
        f"- source hash: {manifest['source_hash']}\n"
        f"- driver hash: {manifest['driver_hash']}\n"
        f"- strategies: {len(names)}\n"
    )
    print(
        f"SPLIT OK symbol={SYMBOL} n={len(rows)} sealed={bounds['sealed'][1] - bounds['sealed'][0]} "
        f"first={manifest['times']['first']} last={manifest['times']['last']} "
        f"strategies={len(names)} sha256={hashes['file']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
