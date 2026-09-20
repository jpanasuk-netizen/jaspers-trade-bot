"""Odds / decision board on :3002 — YES ← open/line → NO (old board layout)."""
from __future__ import annotations

import json
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import state
from .config import config
from .judge import judge
from .market import snapshot
from .spin import live_armed, recent_tape


def _json(h: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()
    h.wfile.write(body)


def _html(h: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    h.send_response(200)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)


def board_payload() -> dict[str, Any]:
    mkt = snapshot()
    j = judge(force=False)
    st = state.current()
    win = mkt.get("window") or j.get("window") or {}
    active = (mkt.get("kalshi") or {}).get("active") or j.get("kalshi_active") or {}
    spot = (mkt.get("spot") or {}).get("price")
    open_px = win.get("open_of_window") or active.get("open_of_window")
    delta = win.get("delta_from_open")
    if delta is None and spot is not None and open_px:
        delta = spot - open_px
    delta_pct = win.get("delta_pct")
    if delta_pct is None and delta is not None and open_px:
        delta_pct = (delta / open_px) * 100.0
    probs = j.get("probabilities") or {}
    yes_ask = win.get("yes_ask") if win.get("yes_ask") is not None else active.get("yes_ask")
    no_ask = win.get("no_ask") if win.get("no_ask") is not None else active.get("no_ask")
    yes_mid = win.get("yes_mid") if win.get("yes_mid") is not None else active.get("yes_mid")
    if yes_mid is None and yes_ask is not None:
        yes_mid = yes_ask

    # O/U style line: settlement vs open. "Over" = YES (above open).
    ou_side = "UNDER" if (delta or 0) < 0 else ("OVER" if (delta or 0) > 0 else "AT")
    tape = recent_tape(12)
    latest_spin = st.get("last_spin") or (tape[0] if tape else None)

    return {
        "ok": True,
        "ts": time.time(),
        "port": 3002,
        "role": "odds_board",
        "liveArmed": live_armed(),
        "window": {
            "ticker": win.get("ticker") or active.get("ticker"),
            "window_id": win.get("window_id") or active.get("window_id"),
            "seconds_left": win.get("seconds_left"),
            "open_of_window": open_px,
            "spot": spot,
            "delta_from_open": delta,
            "delta_pct": delta_pct,
            "ou_side": ou_side,
        },
        "book": {
            "yes_bid": active.get("yes_bid") if active.get("yes_bid") is not None else win.get("yes_bid"),
            "yes_ask": yes_ask,
            "no_bid": active.get("no_bid") if active.get("no_bid") is not None else win.get("no_bid"),
            "no_ask": no_ask,
            "yes_mid": yes_mid,
        },
        "decision": {
            "side": j.get("side"),
            "action": "buy" if j.get("side") == "YES" else "sell" if j.get("side") == "NO" else "hold",
            "trade_action": j.get("trade_action"),
            "conf": j.get("conf"),
            "clear_edge": j.get("clear_edge"),
            "yes_prob": probs.get("yes", probs.get("buy")),
            "no_prob": probs.get("no", probs.get("sell")),
            "hold_prob": probs.get("hold"),
            "reason": j.get("reason"),
            "src": j.get("judge_src"),
            "sentiment_label": j.get("sentiment_label"),
            "polarity_score": j.get("polarity_score"),
            "squeeze_risk_pct": j.get("squeeze_risk_pct"),
        },
        "last_spin": {
            k: (latest_spin or {}).get(k)
            for k in ("ts", "mode", "ticker", "side", "result", "conf", "entry", "reason")
        } if latest_spin else None,
        "windows_decided": [
            {
                "ts": r.get("ts"),
                "ticker": r.get("ticker"),
                "side": r.get("side"),
                "result": r.get("result"),
                "conf": r.get("conf"),
                "entry": r.get("entry"),
                "mode": r.get("mode"),
            }
            for r in tape
            if r.get("result") not in {None, "ALREADY_SPUN"}
        ][:20],
        "totals": (st.get("latest") or {}).get("totals") or {},
    }


class OddsHandler(BaseHTTPRequestHandler):
    server_version = "Jev15mOdds/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[3002] {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path in {"/", "/odds", "/board", "/hud"}:
                _html(self, ODDS_HTML)
                return
            if path in {"/api/odds", "/odds.json", "/api/board"}:
                _json(self, 200, board_payload())
                return
            if path == "/health":
                _json(self, 200, {"ok": True, "port": 3002, "role": "odds_board", "liveArmed": live_armed()})
                return
            _json(self, 404, {"ok": False, "error": path})
        except Exception as exc:  # noqa: BLE001
            _json(self, 500, {"ok": False, "error": str(exc), "trace": traceback.format_exc()[-300:]})


ODDS_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>BTC 15m Odds · :3002</title>
<style>
  :root{--bg:#fff;--panel:#F5F4F1;--border:#ECECEA;--ink:#0A0A0A;--muted:#77776F;--yes:#0B7A48;--yesBg:#D9EEE3;--no:#C2402F;--noBg:#F9DED6;--late:#A16207;--page:#F0EEE9;--mono:"Cascadia Mono",ui-monospace,Menlo,Consolas,monospace;--sans:"Segoe UI",system-ui,sans-serif}
  *{box-sizing:border-box} body{margin:0;background:var(--page);color:var(--ink);font-family:var(--sans)}
  .card{max-width:980px;margin:16px auto;background:var(--bg);border:1px solid var(--border);border-radius:18px;padding:16px 20px 22px}
  header{display:flex;gap:10px;flex-wrap:wrap;align-items:center;font-family:var(--mono);font-size:12px;margin-bottom:14px}
  .brand{font-weight:700;font-family:var(--sans);font-size:15px}
  .chip{background:var(--panel);border:1px solid var(--border);border-radius:999px;padding:3px 10px}
  .spacer{flex:1}
  a.btn{font-family:var(--mono);font-size:12px;text-decoration:none;color:var(--ink);border:1px solid var(--border);background:var(--panel);border-radius:10px;padding:8px 10px}
  .gauge{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:stretch}
  .side{border-radius:16px;border:1px solid var(--border);padding:14px;min-height:150px}
  .side.yes{background:var(--yesBg)}.side.no{background:var(--noBg)}
  .side h2{margin:0;font-family:var(--mono);font-size:22px;letter-spacing:.06em}
  .side.yes h2{color:var(--yes)}.side.no h2{color:var(--no)}
  .px{font-family:var(--mono);font-size:32px;font-weight:700;margin-top:8px}
  .sub{font-family:var(--mono);font-size:12px;color:#3C3C38;margin-top:6px}
  .mid{display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:160px;font-family:var(--mono);text-align:center}
  .mid .line{font-size:28px;font-weight:700}
  .mid .lbl{font-size:11px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px}
  .call{margin-top:14px;border:1px solid var(--border);border-radius:16px;padding:14px;background:var(--panel)}
  .call .word{font-family:var(--mono);font-size:40px;font-weight:700}
  .call .word.yes{color:var(--yes)}.call .word.no{color:var(--no)}.call .word.hold{color:var(--late)}
  .bar{height:10px;background:#F1F0EC;border-radius:999px;overflow:hidden;margin-top:8px}
  .bar>i{display:block;height:100%;width:0}
  table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px;margin-top:14px}
  th,td{padding:6px 8px;border-bottom:1px solid var(--border);text-align:left}
  th{color:var(--muted)}
  .yes{color:var(--yes)}.no{color:var(--no)}.hold{color:var(--late)}
  .tag{font-weight:700}
</style></head><body>
<div class="card">
  <header>
    <span class="brand">‖ BTC 15m Odds Board</span>
    <span class="chip">port 3002</span>
    <span class="chip" id="ticker">—</span>
    <span class="chip" id="mode">PAPER</span>
    <span class="spacer"></span>
    <a class="btn" href="http://127.0.0.1:3000/" target="_blank">Desk :3000</a>
    <a class="btn" href="http://127.0.0.1:3001/" target="_blank">Flow :3001</a>
  </header>
  <div class="gauge">
    <div class="side yes">
      <h2>YES</h2>
      <div class="px" id="yesAsk">—</div>
      <div class="sub">bid <span id="yesBid">—</span> · mid <span id="yesMid">—</span></div>
      <div class="sub">settle ABOVE open</div>
      <div class="sub">model P <span id="yesProb">—</span></div>
    </div>
    <div class="mid">
      <div class="lbl">open / line</div>
      <div class="line" id="openPx">—</div>
      <div class="sub" id="spotLine">spot —</div>
      <div class="sub" id="deltaLine">—</div>
      <div class="sub" id="ouLine">—</div>
      <div class="sub" id="leftLine">—</div>
    </div>
    <div class="side no">
      <h2>NO</h2>
      <div class="px" id="noAsk">—</div>
      <div class="sub">bid <span id="noBid">—</span></div>
      <div class="sub">settle BELOW open</div>
      <div class="sub">model P <span id="noProb">—</span></div>
    </div>
  </div>

  <div class="call">
    <div style="font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#98968E">This window decision</div>
    <div class="word" id="callWord">WAIT</div>
    <div style="font-family:var(--mono);font-size:12px;color:#3C3C38" id="callMeta">—</div>
    <div class="bar"><i id="yesBar" style="background:#34C382"></i></div>
    <div class="bar"><i id="noBar" style="background:#F07860"></i></div>
  </div>

  <table>
    <thead><tr><th>when</th><th>side</th><th>result</th><th>conf</th><th>entry</th><th>ticker</th></tr></thead>
    <tbody id="wins"><tr><td colspan="6">no decided windows yet</td></tr></tbody>
  </table>
  <div style="margin-top:10px;font-family:var(--mono);font-size:11px;color:#77776F" id="foot">—</div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=v=>v==null?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
const pct=v=>v==null?"—":(Number(v)*100).toFixed(1)+"%";
const sec=s=>s==null?"—":(Math.floor(s/60)+":"+String(Math.round(s%60)).padStart(2,"0"));
async function tick(){
  try{
    const d=await fetch("/api/odds").then(r=>r.json());
    const w=d.window||{}, b=d.book||{}, dec=d.decision||{};
    $("ticker").textContent=w.ticker||"—";
    $("mode").textContent=d.liveArmed?"LIVE":"PAPER";
    $("yesAsk").textContent=fmt(b.yes_ask);
    $("yesBid").textContent=fmt(b.yes_bid);
    $("yesMid").textContent=fmt(b.yes_mid);
    $("noAsk").textContent=fmt(b.no_ask);
    $("noBid").textContent=fmt(b.no_bid);
    $("openPx").textContent=fmt(w.open_of_window);
    $("spotLine").textContent="spot "+fmt(w.spot);
    const dl=w.delta_from_open;
    $("deltaLine").textContent=dl==null?"Δ —":("Δ "+(dl>=0?"+":"")+fmt(dl)+(w.delta_pct!=null?" ("+Number(w.delta_pct).toFixed(3)+"%)":""));
    $("deltaLine").className="sub "+(dl==null?"":(dl>=0?"yes":"no"));
    $("ouLine").textContent="O/U "+(w.ou_side||"—");
    $("leftLine").textContent="left "+sec(w.seconds_left);
    $("yesProb").textContent=pct(dec.yes_prob);
    $("noProb").textContent=pct(dec.no_prob);
    const side=(dec.side||"").toUpperCase();
    const word=!side||side==="SKIP"?"HOLD":side;
    const el=$("callWord");
    el.textContent=word;
    el.className="word "+(word==="YES"?"yes":word==="NO"?"no":"hold");
    $("callMeta").textContent=[dec.trade_action,dec.src,"conf "+(dec.conf!=null?Number(dec.conf).toFixed(2):"—"),dec.sentiment_label,dec.reason].filter(Boolean).join(" · ");
    const yp=Math.max(0,Math.min(1,Number(dec.yes_prob)||0));
    const np=Math.max(0,Math.min(1,Number(dec.no_prob)||0));
    $("yesBar").style.width=(yp*100).toFixed(1)+"%";
    $("noBar").style.width=(np*100).toFixed(1)+"%";
    const rows=d.windows_decided||[];
    $("wins").innerHTML=rows.length?rows.map(r=>{
      const s=(r.side||"SKIP").toUpperCase();
      return `<tr><td>${(r.ts||"").slice(11,19)||"—"}</td><td class="tag ${s==="YES"?"yes":s==="NO"?"no":"hold"}">${s}</td><td>${r.result||"—"}</td><td>${r.conf!=null?Number(r.conf).toFixed(2):"—"}</td><td>${r.entry!=null?Number(r.entry).toFixed(2):"—"}</td><td>${(r.ticker||"—").slice(-12)}</td></tr>`;
    }).join(""):`<tr><td colspan="6">no decided windows yet</td></tr>`;
    $("foot").textContent=`fills ${(d.totals&&d.totals.fills)||0} · pnl $${Number((d.totals&&d.totals.pnlUsd)||0).toFixed(4)} · series KXBTC15M · YES=above open · NO=below open`;
  }catch(e){ $("callMeta").textContent="error "+e; }
}
tick(); setInterval(tick,2000);
</script></body></html>
"""


def serve_odds(host: str = "127.0.0.1", port: int = 3002) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), OddsHandler)


def main() -> None:
    server = serve_odds(config.host, 3002)
    print(f"[3002] odds board  http://{config.host}:3002/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
