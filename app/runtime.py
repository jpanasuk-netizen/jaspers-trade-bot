"""Production runtime: fast market/chart loop + slower decision loop."""
from __future__ import annotations

import threading
import time
import traceback

from . import state
from .chart_data import record_tick
from .config import config
from .fast_feed import start_fast_feed
from .market import snapshot
from .quantdinger import btc_research_pack, judgment_overlay


def _chart_poll_sec() -> float:
    try:
        return max(0.5, float(config.chart_poll_sec))
    except Exception:  # noqa: BLE001
        return 1.0


def _decision_poll_sec() -> float:
    try:
        return max(2.0, float(config.poll_sec))
    except Exception:  # noqa: BLE001
        return 8.0


def seed_charts(samples: int = 12) -> int:
    """Warm charts fast — no per-sample QD probes."""
    n = 0
    signal = None
    fair = edge = None
    try:
        ovl = judgment_overlay(btc_research_pack())
        signal = ovl.get("composite_signal")
        fair = ovl.get("fair_yes")
        edge = ovl.get("edge_vs_book")
    except Exception:  # noqa: BLE001
        pass
    for _ in range(max(1, samples)):
        try:
            snap = snapshot()
            win = snap.get("window") or {}
            spot = snap.get("spot") or {}
            ff = snap.get("fast_feed") or {}
            f = ff.get("fair_yes") if ff.get("fair_yes") is not None else fair
            e = ff.get("edge_vs_book") if ff.get("edge_vs_book") is not None else edge
            if e is None and f is not None and win.get("yes_mid") is not None:
                e = float(f) - float(win.get("yes_mid") or 0.5)
            record_tick(
                price=(spot or {}).get("price"),
                yes_mid=win.get("yes_mid"),
                yes_bid=win.get("yes_bid"),
                yes_ask=win.get("yes_ask"),
                no_ask=win.get("no_ask"),
                fair_yes=f,
                edge=e,
                signal=signal,
                side=None,
                conf=None,
                open_of_window=win.get("open_of_window"),
            )
            state.touch_market(snap)
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def market_loop() -> None:
    """High-frequency: keep feed warm + charts ticking every ~1s."""
    print(f"[market] loop start poll={_chart_poll_sec():.1f}s", flush=True)
    try:
        start_fast_feed(poll_sec=max(0.4, float(getattr(config, "fast_feed_sec", 0.6))))
    except Exception as exc:  # noqa: BLE001
        print(f"[market] fast_feed start error: {exc}", flush=True)
    seeded = seed_charts(24)
    print(f"[market] seeded {seeded} chart points", flush=True)
    while True:
        t0 = time.time()
        try:
            snap = snapshot()
            win = snap.get("window") or {}
            spot = snap.get("spot") or {}
            ff = snap.get("fast_feed") or {}
            fair = ff.get("fair_yes")
            edge = ff.get("edge_vs_book")
            if edge is None and fair is not None and win.get("yes_mid") is not None:
                edge = float(fair) - float(win.get("yes_mid") or 0.5)
            signal = None
            try:
                ovl = judgment_overlay(btc_research_pack())
                signal = ovl.get("composite_signal")
                if fair is None:
                    fair = ovl.get("fair_yes")
                if edge is None:
                    edge = ovl.get("edge_vs_book")
            except Exception:  # noqa: BLE001
                pass
            record_tick(
                price=(spot or {}).get("price"),
                yes_mid=win.get("yes_mid"),
                yes_bid=win.get("yes_bid"),
                yes_ask=win.get("yes_ask"),
                no_ask=win.get("no_ask"),
                fair_yes=fair,
                edge=edge,
                signal=signal,
                side=None,
                conf=None,
                open_of_window=win.get("open_of_window"),
            )
            state.touch_market(snap)
        except Exception as exc:  # noqa: BLE001
            print(f"[market] tick error: {type(exc).__name__}: {exc}", flush=True)
        elapsed = time.time() - t0
        time.sleep(max(0.2, _chart_poll_sec() - elapsed))


def decision_loop() -> None:
    """Slower: full judgment + optional spin (risk-gated)."""
    print(
        f"[decision] loop start poll={_decision_poll_sec():.0f}s "
        f"stake=${config.stake_usd:.2f} conf>={config.conf_floor}",
        flush=True,
    )
    while True:
        t0 = time.time()
        try:
            st = state.tick(do_spin=True)
            conn = st.get("connection")
            err = st.get("error")
            mode = "PAPER"
            try:
                from .spin import live_armed

                mode = "LIVE" if live_armed() else "PAPER"
            except Exception:  # noqa: BLE001
                pass
            last = st.get("last_judgment") or {}
            charts = st.get("charts") or {}
            print(
                f"[decision] ok mode={mode} conn={conn} "
                f"side={last.get('side')} route={last.get('route')} "
                f"src={last.get('judge_src')} "
                f"pts={len(charts.get('spot') or [])} err={err}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[decision] loop error: {exc}", flush=True)
            traceback.print_exc()
        elapsed = time.time() - t0
        time.sleep(max(2.0, _decision_poll_sec() - elapsed))


def warmup() -> None:
    """Fast warmup — bind HTTP ASAP, fill charts in background."""
    print("[warmup] starting fast feed…", flush=True)
    try:
        start_fast_feed(poll_sec=0.25)
    except Exception as exc:  # noqa: BLE001
        print(f"[warmup] feed: {exc}", flush=True)
    n = seed_charts(8)
    print(f"[warmup] seeded {n} chart points", flush=True)
    mf = (state.current().get("market_fresh") or {})
    print(f"[warmup] price={mf.get('price')} ticker={mf.get('ticker')}", flush=True)


def start_background() -> list[threading.Thread]:
    threads = []
    t_m = threading.Thread(target=market_loop, daemon=True, name="desk-market")
    t_d = threading.Thread(target=decision_loop, daemon=True, name="desk-decision")
    t_m.start()
    t_d.start()
    threads.extend([t_m, t_d])
    return threads
