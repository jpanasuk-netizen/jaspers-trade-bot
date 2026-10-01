"""Kalshi live orders — only used when LIVE_MARK is armed + credentials exist.

Never prints key material. Reuses RSA-PSS signing pattern from the old live_spin.
"""
from __future__ import annotations

import base64
import json
import math
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .config import config


def taker_fee_usd(price: float, count: float = 1) -> float:
    """Kalshi quadratic taker fee, rounded up to 1¢. Count may be fractional (0.01)."""
    p = min(0.99, max(0.01, float(price)))
    n = max(0.01, float(count))
    raw = 0.07 * n * p * (1.0 - p)
    return math.ceil(raw * 100.0 - 1e-12) / 100.0


def _px01(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x > 1.5:
        x = x / 100.0
    # Kalshi min tick is 1¢. 0.001 is a bad field, not a 1¢ book.
    if x < 0.01 or x > 0.99:
        return None
    return x


def contract_quote(side: str, market: dict[str, Any]) -> dict[str, Any] | None:
    """1-lot YES/NO cost: pay the ask + 1¢-style fee. Not short-YES margin."""
    side = str(side or "").upper()
    yes_ask = _px01(market.get("yes_ask") if market.get("yes_ask") is not None else market.get("yes_ask_dollars"))
    no_ask = _px01(market.get("no_ask") if market.get("no_ask") is not None else market.get("no_ask_dollars"))
    yes_bid = _px01(market.get("yes_bid") if market.get("yes_bid") is not None else market.get("yes_bid_dollars"))
    no_bid = _px01(market.get("no_bid") if market.get("no_bid") is not None else market.get("no_bid_dollars"))
    if no_ask is None and yes_bid is not None:
        no_ask = round(max(0.01, min(0.99, 1.0 - yes_bid)), 4)
    if yes_ask is None and no_bid is not None:
        yes_ask = round(max(0.01, min(0.99, 1.0 - no_bid)), 4)
    if side == "YES":
        ask = yes_ask
        book_side = "bid"
        px = ask
    elif side == "NO":
        ask = no_ask
        book_side = "ask"
        px = round(1.0 - ask, 4) if ask is not None else None  # sell YES at 1 − NO ask
    else:
        return None
    if ask is None or px is None:
        return None
    fee = taker_fee_usd(ask, 1)
    return {
        "side": side,
        "ask": round(ask, 4),
        "px": round(px, 4),
        "book_side": book_side,
        "fee": fee,
        "unit": round(ask, 4),
        "need": round(ask + fee, 4),
        "count": 1,
    }


def cheapest_affordable(market: dict[str, Any], cash: float) -> dict[str, Any] | None:
    """Pick the 1-lot the pennies can actually pay. Prefer cheaper ask."""
    cash_f = float(cash or 0)
    quotes = []
    for side in ("YES", "NO"):
        q = contract_quote(side, market)
        if q:
            quotes.append(q)
    quotes.sort(key=lambda q: q["need"])
    for q in quotes:
        if cash_f + 1e-9 >= q["need"]:
            return q
    return quotes[0] if quotes else None


def sized_quote(
    side: str,
    market: dict[str, Any],
    cash: float,
    max_count: float | None = None,
) -> dict[str, Any] | None:
    """Biggest YES/NO clip that fits this cash budget. V2 allows 0.01 contracts.

    Penny recovery passes max_count=1 so a small bankroll is not bet all at once.
    A normal spin passes the $2 budget and can buy more than one contract.
    """
    q = contract_quote(side, market)
    if not q:
        return None
    ask = float(q["ask"])
    cash_f = float(cash or 0)
    if cash_f < 0.02 or ask < 0.01:
        return None
    room = cash_f / ask
    if max_count is not None:
        room = min(room, float(max_count))
    count = math.floor(room * 100.0) / 100.0
    while count >= 0.01 - 1e-12:
        count = round(count, 2)
        fee = taker_fee_usd(ask, count)
        need = round(count * ask + fee, 4)
        if need <= cash_f + 1e-9:
            out = dict(q)
            out["count"] = count
            out["fee"] = fee
            out["need"] = need
            return out
        count = round(count - 0.01, 2)
    return None


def budget_quote(
    side: str,
    market: dict[str, Any],
    budget_usd: float,
    cash: float,
    take_cents: float = 0.01,
) -> dict[str, Any] | None:
    """Largest clip of this side whose premium plus fee stays within the dollar budget.

    Pays one cent through the quoted ask when that price is still at or under
    the entry ceiling. An IOC parked exactly on a stale ask comes back unfilled.
    """
    q = contract_quote(side, market)
    if not q:
        return None
    quoted = float(q["ask"])
    pay = quoted
    step = max(0.0, float(take_cents or 0))
    if step and quoted + step <= float(config.entry_ceil) + 1e-9:
        pay = round(quoted + step, 2)
    try:
        _budget = float(budget_usd)
    except (TypeError, ValueError):
        _budget = 0.0
    cash_f = float(cash or 0)
    cap = min(_budget, cash_f) if cash_f > 0 else _budget
    if cap < 0.02 or pay < 0.01 or pay > 0.99:
        return None
    count = math.floor((cap / pay) * 100.0) / 100.0
    while count >= 0.01 - 1e-12:
        count = round(count, 2)
        fee = taker_fee_usd(pay, count)
        need = round(count * pay + fee, 4)
        if need <= cap + 1e-9:
            out = dict(q)
            out["quoted_ask"] = round(quoted, 4)
            out["ask"] = round(pay, 4)
            out["count"] = count
            out["fee"] = fee
            out["need"] = need
            out["unit"] = round(pay, 4)
            if str(side).upper() == "YES":
                out["px"] = round(pay, 4)
                out["book_side"] = "bid"
            else:
                out["px"] = round(1.0 - pay, 4)
                out["book_side"] = "ask"
            return out
        count = round(count - 0.01, 2)
    return None

ORDER_PATH = "/trade-api/v2/portfolio/events/orders"
ALT_ORDER_PATHS = (
    "/trade-api/v2/portfolio/events/orders",
)
ALT_HOST = "https://external-api.kalshi.com"
TRANSFER_PATH = "/trade-api/v2/portfolio/intra_exchange_instance_transfer"
# amount unit = centicents ($1 = 10000)


def ensure_shard_funds(key_id, pk, dest_shard: int, min_dollars: float = 0.15) -> dict[str, Any]:
    """Move cash from shard 0 → dest_shard so KXBTC15M (crypto=shard 2) can trade.

    Kalshi's intra-exchange transfer is accepted immediately but the dest shard
    balance updates a beat later — poll before returning dest_cash.
    """
    import time as _time

    if dest_shard is None or int(dest_shard) < 0:
        dest_shard = 2
    dest_shard = int(dest_shard)

    def _shards() -> dict[int, float]:
        _st, bal = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/balance")
        out: dict[int, float] = {}
        for row in bal.get("balance_breakdown") or []:
            try:
                out[int(row.get("exchange_index", -1))] = float(row.get("balance") or 0)
            except (TypeError, ValueError):
                continue
        return out

    shards = _shards()
    have_dest = shards.get(dest_shard, 0.0)
    have_src = shards.get(0, 0.0)
    moved = 0.0
    if have_dest < min_dollars and have_src >= 0.01:
        # Send enough for the clip plus a little fee dust.
        need = max(0.0, min_dollars - have_dest + 0.05)
        send = round(min(max(have_src - 0.01, 0.0), need), 4)
        if send >= 0.01:
            # amount is in CENTICENTS ($1 = 10000) on this endpoint.
            # (send * 100 only moved ~1% of the intended cash — that is why
            # clips came out ~$1 instead of $4.20.)
            amount_cc = int(round(send * 10000))
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
    # Poll — dest balance can lag the POST by a second or two.
    shards2 = shards
    for _ in range(8):
        _time.sleep(0.4)
        shards2 = _shards()
        if shards2.get(dest_shard, 0.0) >= min_dollars:
            break
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


_EX_CACHE: dict[str, int] = {}


def _resolve_market_ex(key_id, pk, ticker: str, market: dict[str, Any] | None) -> int:
    """KXBTC15M binary markets live on exchange_index 2 (crypto events)."""
    for cand in ((market or {}).get("exchange_index"),):
        try:
            if cand is not None:
                return int(cand)
        except (TypeError, ValueError):
            pass
    cached = _EX_CACHE.get(str(ticker or ""))
    if cached is not None:
        return cached
    try:
        _st, data = _kreq(key_id, pk, "GET", f"/trade-api/v2/markets/{ticker}")
        ex = (data.get("market") or {}).get("exchange_index")
        if ex is not None:
            value = int(ex)
            if ticker:
                _EX_CACHE[str(ticker)] = value
            return value
    except Exception:  # noqa: BLE001
        pass
    return 2


def _extract_order(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    o = data.get("order")
    if isinstance(o, dict):
        return o
    orders = data.get("orders")
    if isinstance(orders, list) and orders and isinstance(orders[0], dict):
        return orders[0]
    return data


def _fill_count(order: dict[str, Any]) -> float:
    raw = order.get("fill_count") or order.get("filled_count") or 0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _kreq_soft(key_id, pk, method: str, path: str, body: dict | None = None, base: str | None = None) -> tuple[int | None, dict[str, Any]]:
    try:
        st, data = _kreq(key_id, pk, method, path, body, base=base)
        return st, data if isinstance(data, dict) else {"raw": data}
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        parsed: dict[str, Any] = {"error": msg[:400]}
        brace = msg.find("{")
        if brace >= 0:
            try:
                blob = json.loads(msg[brace:])
                if isinstance(blob, dict):
                    parsed = blob
                    parsed.setdefault("error", blob.get("error") or msg[:400])
            except Exception:  # noqa: BLE001
                pass
        code = None
        if " -> " in msg:
            try:
                code = int(msg.split(" -> ", 1)[1].split(" ", 1)[0])
            except (TypeError, ValueError):
                code = 400
        return code, parsed


def _err_code(data: dict[str, Any]) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or "")
    if isinstance(err, str) and "insufficient_balance" in err:
        return "insufficient_balance"
    if isinstance(err, str) and "market_not_found" in err:
        return "market_not_found"
    return ""


def _submit_kalshi_order(key_id, pk, body: dict[str, Any]) -> tuple[int | None, dict[str, Any], dict[str, Any]]:
    """One real order. Retry only on market_not_found. A fill wins even on HTTP 400."""
    last_err = None
    data: dict[str, Any] = {}
    st = None
    used = dict(body)
    bases = [ex for ex in (body.get("exchange_index"), 2, -1, None)]
    seen: set[str] = set()
    for host in (ALT_HOST, config.kalshi_trade):
        for opath in ALT_ORDER_PATHS:
            for ex in bases:
                payload = dict(body)
                payload["client_order_id"] = str(uuid.uuid4())
                if ex is None:
                    payload.pop("exchange_index", None)
                else:
                    payload["exchange_index"] = ex
                sig = f"{host}|{opath}|{ex}"
                if sig in seen:
                    continue
                seen.add(sig)
                st, data = _kreq_soft(key_id, pk, "POST", opath, payload, base=host)
                order = _extract_order(data)
                payload["_order_path"] = opath
                payload["_host"] = host
                if _fill_count(order) > 0:
                    data = dict(data)
                    data["order"] = order
                    data.pop("error", None)
                    return st, data, payload
                code = _err_code(data)
                ok_http = st is not None and int(st) < 300 and not data.get("error")
                if ok_http:
                    return st, data, payload
                last_err = str(data.get("error") or data)[:400]
                used = payload
                # V1 path is dead. Skip it and try the V2 events path.
                if code in {"deprecated_v1_order_endpoint"}:
                    continue
                if code == "insufficient_balance":
                    return st, data, payload
                if code not in {"market_not_found", "not_found"} and st not in {404, None}:
                    return st, data, payload
    if not isinstance(data, dict):
        data = {"error": last_err or "non-json"}
    elif last_err and not data.get("error"):
        data["error"] = last_err
    return st, data, used


def fetch_positions() -> dict[str, dict[str, Any]]:
    """Live positions by ticker: count / market_value / realized_pnl.

    Used to notice a customer sell in the Kalshi app (position vanishes or
    shrinks without our bot placing an exit).
    """
    try:
        key_id, pk = load_creds()
        _st, data = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/positions?limit=200")
    except Exception as exc:  # noqa: BLE001
        return {"_error": {"message": str(exc)[:160]}}
    out: dict[str, dict[str, Any]] = {}
    for p in data.get("market_positions") or data.get("positions") or []:
        if not isinstance(p, dict):
            continue
        ticker = str(p.get("ticker") or p.get("market_ticker") or "")
        if not ticker:
            continue
        try:
            pos = float(p.get("position") or p.get("quantity") or 0)
        except (TypeError, ValueError):
            pos = 0.0
        try:
            rp = p.get("realized_pnl_dollars", p.get("realized_pnl"))
            rp_f = float(rp) if rp is not None else None
        except (TypeError, ValueError):
            rp_f = None
        try:
            mv = p.get("market_value_dollars", p.get("market_value"))
            mv_f = float(mv) if mv is not None else None
        except (TypeError, ValueError):
            mv_f = None
        out[ticker] = {"count": pos, "realized_pnl": rp_f, "market_value": mv_f}
    return out


def place_order(
    ticker: str,
    side: str,
    market: dict[str, Any],
    stake_usd: float | None = None,
    count: float | None = None,
    limit_px: float | None = None,
) -> dict[str, Any]:
    key_id, pk = load_creds()
    q = contract_quote(side, market)
    if not q:
        raise RuntimeError(f"no {side} ask on book")
    px = float(limit_px) if limit_px is not None else q["px"]
    book_side = q["book_side"]
    unit = q["unit"]
    need = q["need"]

    stake = float(stake_usd if stake_usd is not None else config.stake_usd)

    market_ex = _resolve_market_ex(key_id, pk, ticker, market)
    try:
        from . import martingale as mg

        avail = float(mg.kalshi_cash() or 0)
        if avail <= 0:
            _st_b, bal = _kreq(key_id, pk, "GET", "/trade-api/v2/portfolio/balance")
            raw = float(bal.get("balance_dollars") or 0)
            avail = raw / 100.0 if raw > 50 else raw
    except Exception:  # noqa: BLE001
        avail = float(stake or 0)

    if count is not None:
        count_f = max(0.01, round(float(count), 2))
        if str(side).upper() == "YES":
            pay = float(px)
        else:
            pay = round(1.0 - float(px), 4)
        fee = taker_fee_usd(pay, count_f)
        need = round(count_f * pay + fee, 4)
        q = dict(q)
        q["count"] = count_f
        q["fee"] = fee
        q["need"] = need
        count = count_f
    else:
        sized = sized_quote(side, market, min(float(stake or avail), avail if avail else float(stake or 0)))
        if sized:
            q = sized
            count = float(sized["count"])
            need = float(sized["need"])
            unit = sized["unit"]
            px = sized["px"]
            book_side = sized["book_side"]
        else:
            count = 0.01
            need = q["need"]

    fund_info = ensure_shard_funds(key_id, pk, market_ex, min_dollars=max(0.02, float(need or 0.02)))

    if avail + 1e-9 < float(need):
        raise RuntimeError(
            f"{count} {side} needs ${need:.2f} (ask {unit:.2f}+fee {q['fee']:.2f}) "
            f"cash=${avail:.2f} shard={market_ex}"
        )

    ex = market_ex

    # AGGRESSIVE_TAKE: IOC at the ask misses when the book flickers.
    # Pay a tick over the ask so the order actually crosses.
    try:
        px_take = min(0.99, round(float(px) + 0.01, 4))
    except (TypeError, ValueError):
        px_take = px
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": book_side,
        "count": f"{float(count):.2f}",
        "price": f"{px_take:.4f}",
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

    st, data, body = _submit_kalshi_order(key_id, pk, body)

    order = _extract_order(data)
    fill_n = _fill_count(order)
    fill_count = str(order.get("fill_count") or fill_n)
    filled = fill_n > 0
    if filled:
        data = dict(data or {})
        data["order"] = order
        data.pop("error", None)
    if not filled and data.get("error"):
        raise RuntimeError(str(data["error"])[:400])

    # IOC only. A resting order can fill later, after the panel no longer agrees.
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


def close_position(
    ticker: str,
    side: str,
    count: float,
    market: dict[str, Any],
) -> dict[str, Any]:
    """Sell an open ticket. IOC and reduce-only, so it cannot flip into a new bet.

    YES is sold at the bid. NO is closed by buying YES at the ask, which is
    the same cash as hitting the NO bid.
    """
    side_u = str(side or "").upper()
    count_f = round(float(count), 2)
    if side_u == "YES":
        px = _px01(market.get("yes_bid"))
        book_side = "ask"
    elif side_u == "NO":
        px = _px01(market.get("yes_ask"))
        if px is None:
            no_bid = _px01(market.get("no_bid"))
            px = round(1.0 - no_bid, 4) if no_bid is not None else None
        book_side = "bid"
    else:
        raise RuntimeError(f"cannot close side {side}")
    if px is None or count_f < 0.01:
        raise RuntimeError("no exit price or size")
    key_id, pk = load_creds()
    ex = _resolve_market_ex(key_id, pk, ticker, market)
    body = {
        "ticker": ticker,
        "client_order_id": str(uuid.uuid4()),
        "side": book_side,
        "count": f"{count_f:.2f}",
        "price": f"{float(px):.4f}",
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": True,
        "reduce_only": True,
        "exchange_index": ex,
    }
    st, data, sent = _submit_kalshi_order(key_id, pk, body)
    order = _extract_order(data)
    fill_n = _fill_count(order)
    # RETRY_FILL: one more IOC at +2 ticks if the first pass missed.
    if fill_n <= 0:
        try:
            px2 = min(0.99, round(float(px) + 0.02, 4))
            body2 = dict(body)
            body2["price"] = f"{px2:.4f}"
            body2["client_order_id"] = str(uuid.uuid4())
            st, data, sent = _submit_kalshi_order(key_id, pk, body2)
            order = _extract_order(data)
            fill_n = _fill_count(order)
        except Exception:
            pass
    return {
        "simulated": False,
        "http_status": st,
        "body": sent,
        "response": data,
        "count": count_f,
        "price": float(px),
        "book_side": book_side,
        "fill_count": str(order.get("fill_count") or fill_n),
        "filled": fill_n > 0,
        "api": "v2_create_order",
        "reduce_only": True,
        "error": data.get("error") if isinstance(data, dict) else None,
    }

