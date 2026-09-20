"""Kalshi live orders — only used when LIVE_MARK is armed + credentials exist.

Never prints key material. Reuses RSA-PSS signing pattern from the old live_spin.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .config import config

ORDER_PATH = "/trade-api/v2/portfolio/events/orders"
ALT_ORDER_PATHS = (
    "/trade-api/v2/portfolio/events/orders",
)
ALT_HOST = "https://external-api.kalshi.com"
TRANSFER_PATH = "/trade-api/v2/portfolio/intra_exchange_instance_transfer"
# amount unit = centicents ($1 = 10000)


def ensure_shard_funds(key_id, pk, dest_shard: int, min_dollars: float = 0.15) -> dict[str, Any]:
    """Move cash from shard 0 → dest_shard so KXBTC15M (crypto=shard 2) can trade."""
    if dest_shard is None or int(dest_shard) < 0:
        dest_shard = 2
    dest_shard = int(dest_shard)
    _st, bal = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/balance")
    shards = {}
    for row in bal.get("balance_breakdown") or []:
        try:
            shards[int(row.get("exchange_index", -1))] = float(row.get("balance") or 0)
        except (TypeError, ValueError):
            continue
    have_dest = shards.get(dest_shard, 0.0)
    have_src = shards.get(0, 0.0)
    moved = 0.0
    if have_dest < min_dollars and have_src > 0.02:
        # leave a dust buffer on shard 0
        send = min(have_src - 0.01, max(0.0, min_dollars - have_dest + 0.05))
        send = round(send, 4)
        if send >= 0.02:
            amount_cc = int(round(send * 10000))  # centicents
            body = {
                "source": "event_contract",
                "destination": "event_contract",
                "amount": amount_cc,
                "source_exchange_shard": 0,
                "destination_exchange_shard": dest_shard,
            }
            try:
                _st_t, data = _kreq(key_id, pk, "POST", TRANSFER_PATH, body, base=config.kalshi_trade)
                moved = send
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)[:200], "shards": shards, "dest_shard": dest_shard}
    _st2, bal2 = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/balance")
    shards2 = {}
    for row in bal2.get("balance_breakdown") or []:
        try:
            shards2[int(row.get("exchange_index", -1))] = float(row.get("balance") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "ok": True,
        "moved_usd": moved,
        "dest_shard": dest_shard,
        "shards_before": shards,
        "shards_after": shards2,
        "dest_cash": shards2.get(dest_shard, 0.0),
    }


def _find_key_id() -> str:
    if config.kalshi_api_key_id:
        return config.kalshi_api_key_id
    for folder in config.secrets_dir_candidates:
        p = folder / "key_id.txt"
        if p.is_file():
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
    return ""


def _find_pem_text() -> str:
    if config.kalshi_private_key_path:
        p = Path(config.kalshi_private_key_path).expanduser()
        if p.is_file():
            return p.read_text(encoding="utf-8")
    for folder in config.secrets_dir_candidates:
        for name in ("kalshi-private-key.pem", "private-key.pem", "kalshi.pem"):
            p = folder / name
            if p.is_file():
                return p.read_text(encoding="utf-8")
    return ""


def load_creds() -> tuple[str, Any]:
    key_id = _find_key_id()
    pem = _find_pem_text()
    if not key_id or not pem:
        raise RuntimeError("missing Kalshi key_id or PEM (env or secrets dirs)")
    if "BEGIN" not in pem:
        raise RuntimeError("PEM does not look valid")
    from cryptography.hazmat.primitives import serialization  # type: ignore

    pk = serialization.load_pem_private_key(pem.encode(), password=None)
    return key_id, pk


def _sign(key_id: str, pk: Any, method: str, path: str) -> dict[str, str]:
    from cryptography.hazmat.primitives import hashes  # type: ignore
    from cryptography.hazmat.primitives.asymmetric import padding  # type: ignore

    path_only = path.split("?")[0]
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method}{path_only}".encode()
    sig = pk.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "jev-15m-kalshi-bot/1.0",
    }


def _kreq(key_id: str, pk: Any, method: str, path: str, body: dict | None = None, base: str | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    host = base or config.kalshi_trade
    req = urllib.request.Request(host + path, data=data, headers=_sign(key_id, pk, method, path), method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        err = exc.read().decode() if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"{method} {path} -> {exc.code} {err[:400]}") from exc


def place_order(
    ticker: str,
    side: str,
    market: dict[str, Any],
    stake_usd: float | None = None,
) -> dict[str, Any]:
    key_id, pk = load_creds()
    yes_ask = float(market.get("yes_ask") or market.get("yes_ask_dollars") or 0)
    no_ask = float(market.get("no_ask") or market.get("no_ask_dollars") or 0)
    yes_bid = market.get("yes_bid") if market.get("yes_bid") is not None else market.get("yes_bid_dollars")
    yes_bid = float(yes_bid) if yes_bid not in (None, "") else max(0.01, 1.0 - (no_ask or 0.5))

    # V2 quotes on the YES book only
    if side == "YES":
        # buy YES — bid near ask
        px = round(min(0.99, max(0.01, yes_ask + 0.01 if yes_ask else 0.5)), 4)
        book_side = "bid"
        entry_ref = yes_ask or px
        # capital at risk ≈ px per contract
        unit = px
    else:
        # NO = sell YES — CROSS the book: price at bid or one tick below
        bid = float(yes_bid) if yes_bid not in (None, "") else None
        if bid is None:
            bid = max(0.01, 1.0 - (no_ask or 0.5))
        px = round(max(0.01, min(0.99, bid - 0.01)), 4)  # aggressive taker
        book_side = "ask"
        entry_ref = no_ask or (1.0 - px)
        unit = max(px, 1.0 - px)

    stake = float(stake_usd if stake_usd is not None else config.stake_usd)

    # live cash — fund the market's exchange shard first (crypto KXBTC15M = shard 2)
    market_ex = market.get("exchange_index")
    try:
        market_ex = int(market_ex) if market_ex is not None else 2
    except (TypeError, ValueError):
        market_ex = 2
    fund_info = ensure_shard_funds(key_id, pk, market_ex, min_dollars=max(0.2, float(stake or 0.2)))
    try:
        _st_b, bal = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/balance")
        avail = 0.0
        for row in bal.get("balance_breakdown") or []:
            try:
                if int(row.get("exchange_index", -1)) == market_ex:
                    avail = float(row.get("balance") or 0)
                    break
            except (TypeError, ValueError):
                continue
        if avail <= 0:
            raw = float(bal.get("balance_dollars") or 0)
            avail = raw / 100.0 if raw > 50 else raw
        # Fill-first: if planned stake can't cover margin but cash can, use cash
        if unit > stake and avail >= unit:
            stake = min(avail * 0.97, max(unit, stake))
        else:
            stake = min(stake, max(0.0, avail * 0.95))
    except Exception:  # noqa: BLE001
        pass

    if unit <= 0:
        unit = 0.05
    count = max(1, int(stake / max(0.05, unit)))
    while count > 1 and count * unit > stake * 1.05:
        count -= 1
    if count == 1 and unit > stake * 1.02:
        raise RuntimeError(
            f"1 contract needs ~${unit:.2f} (side={side} px={px:.4f}) but stake/cash=${stake:.2f} "
            f"shard={market_ex} fund={fund_info}"
        )

    ex = market_ex

    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": book_side,
        "count": f"{float(count):.2f}",
        "price": f"{px:.4f}",
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": True,
        "reduce_only": False,
        "exchange_index": ex,
    }

    # cancel resting on this ticker
    try:
        _st_o, od = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/orders?limit=20&status=open")
        for o in (od.get("orders") or []):
            if str(o.get("ticker") or "") == ticker and o.get("order_id"):
                try:
                    _kreq(key_id, pk, "DELETE", f"/trade-api/v2/portfolio/orders/{o['order_id']}")
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass

    last_err = None
    data = None
    st = None
    for host in (config.kalshi_trade, ALT_HOST):
        for opath in ALT_ORDER_PATHS:
            try:
                st, data = _kreq(key_id, pk, "POST", opath, body, base=host)
                if isinstance(data, dict) and not data.get("error"):
                    body["_order_path"] = opath
                    break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                data = {"error": last_err[:400], "host": host, "path": opath}
                st = None
        if isinstance(data, dict) and not data.get("error"):
            break
    if not isinstance(data, dict):
        data = {"error": last_err or "non-json"}

    order = data.get("order") if isinstance(data.get("order"), dict) else data
    fill_count = str(order.get("fill_count") or "0") if isinstance(order, dict) else "0"
    try:
        filled = float(fill_count) > 0
    except (TypeError, ValueError):
        filled = False
    if not filled and data.get("error"):
        raise RuntimeError(str(data["error"])[:400])

    # IOC missed — rest GTC at the same (or more aggressive) price so it can fill
    if not filled and not (isinstance(data, dict) and data.get("error")):
        gtc = dict(body)
        gtc["client_order_id"] = str(uuid.uuid4())
        gtc["time_in_force"] = "good_till_canceled"
        for host in (config.kalshi_trade, ALT_HOST):
            try:
                st_g, data_g = _kreq(key_id, pk, "POST", ORDER_PATH, gtc, base=host)
                order_g = data_g.get("order") if isinstance(data_g.get("order"), dict) else data_g
                fill_g = str((order_g or {}).get("fill_count") or "0")
                if float(fill_g or 0) > 0:
                    data = data_g
                    order = order_g
                    fill_count = fill_g
                    filled = True
                    body = gtc
                    st = st_g
                    break
                data = {"ioc": data, "gtc": data_g, "rested": True}
            except Exception as exc:  # noqa: BLE001
                data = {"ioc_fill": fill_count, "gtc_error": str(exc)[:200]}

    return {
        "simulated": False,
        "http_status": st,
        "body": body,
        "response": data,
        "count": count,
        "price": px,
        "book_side": book_side,
        "est_cost": round(count * unit, 4),
        "fill_count": fill_count,
        "filled": filled,
        "fill_price": float(order.get("average_fill_price") or px) if isinstance(order, dict) else px,
        "api": "v2_create_order",
        "error": data.get("error") if isinstance(data, dict) else None,
    }

