"""Spike strategy — ported from jarrodwatts/jev-trader e3dfeca.

Wait for a sharp BTC move (1m / 3m). Jev names YES, NO, or stay out.
A live spike is allowed to fire before the last-three-minutes clock.
Fade/follow shadows stay paper so we can tell whether Jev added anything.

Kalshi KXBTC15M mapping:
  up spike   → follow=YES, fade=NO
  down spike → follow=NO,  fade=YES
Exits for shadows: settle at window close, or cut when the other side prints
above SPIKE_CUT_OTHER_PCT, or after SPIKE_MAX_HOLD_MIN.
Live still pays ENTRY_CEIL, tape, and Jev's named side — no flip.
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Optional

from .config import config

SPIKE_LOG = Path(getattr(config, "data_dir", Path("data"))) / "spike.jsonl"


def _now() -> float:
    return time.time()


def _round(x: float, d: int = 3) -> float:
    return round(float(x), d)


@dataclass
class SpikeTrigger:
    window: str  # "1m" | "3m"
    direction: str  # "up" | "down"
    move_pct: float
    from_price: float


@dataclass
class OpenPos:
    who: str  # jev | fade | follow
    side: str  # YES | NO
    entry: float
    opened_at: float
    spike_block: int
    spike_dir: str


@dataclass
class SpikeTrader:
    """Paper-only spike book. One position per who (jev / fade / follow)."""

    decide: Callable[[dict[str, Any]], dict[str, Any]]
    move_1m_pct: float = 0.5
    move_3m_pct: float = 0.8
    cooldown_sec: float = 180.0
    max_hold_min: float = 15.0
    cut_other_pct: float = 0.70
    mids: Deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=360))
    open: dict[str, OpenPos] = field(default_factory=dict)
    cooldown_until: float = 0.0
    block: int = 0
    realized: dict[str, float] = field(default_factory=lambda: {"jev": 0.0, "fade": 0.0, "follow": 0.0})
    closed: dict[str, int] = field(default_factory=lambda: {"jev": 0, "fade": 0, "follow": 0})
    skips: int = 0
    spikes: int = 0

    def describe(self) -> str:
        return (
            f"spike · trigger {self.move_1m_pct}% in 1m or {self.move_3m_pct}% in 3m · "
            f"cut when other side > {self.cut_other_pct:.0%} · max hold {self.max_hold_min:.0f} min · "
            f"cooldown {self.cooldown_sec:.0f}s · live Jev fire · shadows fade/follow paper · log {SPIKE_LOG.name}"
        )

    def detect(self, mid: float) -> Optional[SpikeTrigger]:
        mids = list(self.mids)
        if len(mids) < 60:
            return None
        # sample every second; 1m = last 60, 3m = last 180
        def past(n: int) -> Optional[float]:
            if len(mids) <= n:
                return None
            return mids[-1 - n][1]

        p1 = past(60)
        p3 = past(180)
        if p1:
            r1 = (mid / p1 - 1.0) * 100.0
            if abs(r1) >= self.move_1m_pct:
                return SpikeTrigger("1m", "up" if r1 > 0 else "down", _round(r1), p1)
        if p3:
            r3 = (mid / p3 - 1.0) * 100.0
            if abs(r3) >= self.move_3m_pct:
                return SpikeTrigger("3m", "up" if r3 > 0 else "down", _round(r3), p3)
        return None

    def _exit_reason(self, o: OpenPos, yes_ask: float, no_ask: float, now: float) -> Optional[str]:
        other = no_ask if o.side == "YES" else yes_ask
        if other is not None and other >= self.cut_other_pct:
            return "cut-other-side"
        if (now - o.opened_at) >= self.max_hold_min * 60.0:
            return "time"
        return None

    def _close(self, o: OpenPos, yes_ask: float, no_ask: float, reason: str, now: float) -> dict[str, Any]:
        self.open.pop(o.who, None)
        # paper exit at the touch: sell YES at yes_bid≈1-no_ask, buy back NO at no_ask
        if o.side == "YES":
            exit_px = 1.0 - (no_ask if no_ask is not None else 0.5)
        else:
            exit_px = 1.0 - (yes_ask if yes_ask is not None else 0.5)
        pnl = exit_px - o.entry
        self.realized[o.who] += pnl
        self.closed[o.who] += 1
        row = {
            "type": "trade",
            "who": o.who,
            "side": o.side,
            "spike_dir": o.spike_dir,
            "spike_block": o.spike_block,
            "opened_at": o.opened_at,
            "closed_at": now,
            "held_min": _round((now - o.opened_at) / 60.0, 2),
            "entry": o.entry,
            "exit": exit_px,
            "reason": reason,
            "pnl_contract": _round(pnl, 4),
        }
        self._log(row)
        return row

    def _open(self, who: str, side: str, ask: float, spike: SpikeTrigger) -> OpenPos:
        o = OpenPos(who=who, side=side, entry=ask, opened_at=_now(), spike_block=self.block, spike_dir=spike.direction)
        self.open[who] = o
        return o

    def _log(self, row: dict[str, Any]) -> None:
        try:
            SPIKE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with SPIKE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
        except Exception:
            pass

    def on_tick(
        self,
        mid: float,
        yes_ask: float,
        no_ask: float,
        window_secs_left: Optional[float] = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """One paper tick. Returns a note + snapshot for the HUD/ledger."""
        self.block += 1
        now = _now()
        self.mids.append((now, mid))
        note = ""

        # exits first
        for o in list(self.open.values()):
            r = self._exit_reason(o, yes_ask, no_ask, now)
            if r:
                res = self._close(o, yes_ask, no_ask, r, now)
                if o.who == "jev":
                    note = f"SPIKE EXIT {r} {res['pnl_contract']:+.3f} contract"

        spike = None
        if now >= self.cooldown_until:
            spike = self.detect(mid)
        if spike and window_secs_left is not None and window_secs_left < 60:
            spike = None  # too late to open in this window

        if spike:
            self.spikes += 1
            self.cooldown_until = now + self.cooldown_sec
            follow = "YES" if spike.direction == "up" else "NO"
            fade = "NO" if spike.direction == "up" else "YES"
            for who, side in (("fade", fade), ("follow", follow)):
                if who not in self.open:
                    ask = yes_ask if side == "YES" else no_ask
                    if ask is not None and 0.01 <= ask <= 0.99:
                        self._open(who, side, float(ask), spike)
            decision = {"action": "hold", "probabilities": {"yes": 0, "no": 0, "hold": 1}}
            if "jev" not in self.open:
                payload = {
                    "spike": {
                        "window": spike.window,
                        "direction": spike.direction,
                        "move_pct": spike.move_pct,
                        "from_price": spike.from_price,
                    },
                    "mid": mid,
                    "yes_ask": yes_ask,
                    "no_ask": no_ask,
                    "window_secs_left": window_secs_left,
                    "returns": extra.get("returns"),
                    **{k: v for k, v in extra.items() if k != "returns"},
                }
                try:
                    decision = self.decide(payload) or decision
                except Exception as exc:  # noqa: BLE001
                    decision = {"action": "hold", "error": str(exc)[:120]}
                act = str(decision.get("action") or "hold").upper()
                if act in {"YES", "NO", "BUY", "SELL"}:
                    side = {"BUY": "YES", "YES": "YES", "SELL": "NO", "NO": "NO"}[act]
                    ask = yes_ask if side == "YES" else no_ask
                    if ask is not None and 0.01 <= ask <= 0.99:
                        self._open("jev", side, float(ask), spike)
                        style = "follow" if side == follow else "fade"
                        note = f"SPIKE {spike.direction} {spike.move_pct:.2f}% in {spike.window} -> {side} ({style})"
                    else:
                        note = f"SPIKE {spike.direction} -> {side} but no ask"
                        self.skips += 1
                else:
                    self.skips += 1
                    note = f"SPIKE {spike.direction} {spike.move_pct:.2f}% in {spike.window} -> stay out"
            else:
                note = f"SPIKE {spike.direction} {spike.move_pct:.2f}% in {spike.window} (in a position: not asked)"
            self._log(
                {
                    "type": "spike",
                    "block": self.block,
                    "ts": now,
                    "window": spike.window,
                    "direction": spike.direction,
                    "move_pct": spike.move_pct,
                    "from_price": spike.from_price,
                    "mid": mid,
                    "asked": "jev" not in self.open or note.startswith("SPIKE") and "stay" in note or "->" in note,
                    "jev": decision,
                    "window_secs_left": window_secs_left,
                }
            )

        return {
            "note": note,
            "block": self.block,
            "spikes": self.spikes,
            "skips": self.skips,
            "open": {k: {"side": v.side, "entry": v.entry} for k, v in self.open.items()},
            "realized": dict(self.realized),
            "closed": dict(self.closed),
            "describe": self.describe(),
        }


def jev_spike_decide(payload: dict[str, Any]) -> dict[str, Any]:
    """Ask the desk judge after a spike. Falls back to hold if Jev is down."""
    try:
        from .judge import judge as _judge

        j = _judge(force=True)
        side = str(j.get("side") or "hold").upper()
        conf = float(j.get("conf") or 0)
        # Spike question is long/short/stay-out after a sharp move — reuse Jev's side.
        if side not in {"YES", "NO"} or conf < float(getattr(config, "conf_floor", 0.55)):
            return {"action": "hold", "probabilities": {"yes": 0, "no": 0, "hold": 1}, "conf": conf, "src": j.get("judge_src")}
        return {
            "action": side,
            "probabilities": {"yes": conf if side == "YES" else 0, "no": conf if side == "NO" else 0, "hold": 1 - conf},
            "conf": conf,
            "src": j.get("judge_src"),
            "reason": j.get("reason"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"action": "hold", "error": str(exc)[:120]}


def run_dry(ticks: int = 60, sleep_s: float = 2.0) -> None:
    """Standalone dry-run loop using public spot + book. Never live."""
    from .market import fetch_btc_spot, fetch_kalshi_btc_book

    trader = SpikeTrader(decide=jev_spike_decide)
    print(trader.describe(), flush=True)
    for i in range(ticks):
        try:
            spot = fetch_btc_spot()
            book = fetch_kalshi_btc_book()
            active = book.get("active") or {}
            mid = float(spot.get("price") or 0)
            yes_ask = active.get("yes_ask")
            no_ask = active.get("no_ask")
            secs = active.get("seconds_left")
            if mid and yes_ask is not None and no_ask is not None:
                snap = trader.on_tick(mid, float(yes_ask), float(no_ask), window_secs_left=float(secs) if secs is not None else None)
                if snap.get("note"):
                    print(f"[{i}] {snap['note']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] err {exc}", flush=True)
        time.sleep(sleep_s)


if __name__ == "__main__":
    run_dry()
