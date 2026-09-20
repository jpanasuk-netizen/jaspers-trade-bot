"""Flow backend on :3001 — market tape + /jev judgment (old JAP layout)."""
from __future__ import annotations

import json
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import state
from .config import config
from .judge import judge
from .market import snapshot
from .spin import evaluate_spin, live_armed, recent_tape


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


class FlowHandler(BaseHTTPRequestHandler):
    server_version = "Jev15mFlow/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[3001] {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        qs = parse_qs(urlparse(self.path).query)
        try:
            if path in {"/", "/hud", "/flow"}:
                _html(self, FLOW_HTML)
                return
            if path in {"/jev", "/api/jev"}:
                force = (qs.get("force") or ["0"])[0] in {"1", "true", "yes"}
                j = judge(force=force)
                # Old live_spin / dashboard contract
                _json(self, 200, {
                    "ok": j.get("ok", True),
                    "action": "buy" if j.get("side") == "YES" else "sell" if j.get("side") == "NO" else "hold",
                    "side": j.get("side"),
                    "conf": j.get("conf"),
                    "clear_edge": j.get("clear_edge"),
                    "reason": j.get("reason"),
                    "probabilities": j.get("probabilities"),
                    "trade_action": j.get("trade_action"),
                    "src": j.get("judge_src"),
                    "model": j.get("model"),
                    "spot": j.get("spot"),
                    "open_of_window": j.get("open_of_window"),
                    "delta_from_open": j.get("delta_from_open"),
                    "delta_pct": j.get("delta_pct"),
                    "yes_mid": j.get("yes_mid"),
                    "window": j.get("window"),
                    "sentiment_label": j.get("sentiment_label"),
                    "polarity_score": j.get("polarity_score"),
                    "squeeze_risk_pct": j.get("squeeze_risk_pct"),
                    "social_stats": j.get("social_stats"),
                    "judged_at": j.get("judged_at"),
                    "liveArmed": live_armed(),
                })
                return
            if path in {"/market", "/api/market", "/tape"}:
                _json(self, 200, snapshot())
                return
            if path in {"/decisions", "/api/decisions"}:
                _json(self, 200, {"ok": True, "tape": recent_tape(50), "liveArmed": live_armed()})
                return
            if path in {"/state", "/api/state"}:
                _json(self, 200, state.current())
                return
            if path == "/api/spin":
                rec = evaluate_spin(force_judge=True)
                _json(self, 200, {"ok": True, "spin": rec})
                return
            if path == "/health":
                _json(self, 200, {
                    "ok": True, "port": 3001, "role": "flow",
                    "series": config.series_ticker, "liveArmed": live_armed(),
                })
                return
            _json(self, 404, {"ok": False, "error": path})
        except Exception as exc:  # noqa: BLE001
            _json(self, 500, {"ok": False, "error": str(exc), "trace": traceback.format_exc()[-300:]})


FLOW_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>BTC 15m Flow · :3001</title>
<style>
  :root{--bg:#fff;--panel:#F5F4F1;--border:#ECECEA;--ink:#0A0A0A;--muted:#77776F;--yes:#0B7A48;--no:#C2402F;--page:#F0EEE9;--mono:"Cascadia Mono",ui-monospace,Menlo,Consolas,monospace;--sans:"Segoe UI",system-ui,sans-serif}
  *{box-sizing:border-box} body{margin:0;background:var(--page);color:var(--ink);font-family:var(--sans)}
  .card{max-width:1100px;margin:16px auto;background:var(--bg);border:1px solid var(--border);border-radius:18px;padding:16px 20px 20px}
  header{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px;font-family:var(--mono);font-size:12px}
  .brand{font-weight:700;font-family:var(--sans);font-size:15px}
  .chip{background:var(--panel);border:1px solid var(--border);border-radius:999px;padding:3px 10px}
  .spacer{flex:1}
  a.btn{font-family:var(--mono);font-size:12px;text-decoration:none;color:var(--ink);border:1px solid var(--border);background:var(--panel);border-radius:10px;padding:8px 10px}
  a.btn:hover{border-color:#98968E}
  .grid{display:grid;grid-template-columns:1.2fr 1fr;gap:12px}
  @media(max-width:800px){.grid{grid-template-columns:1fr}}
  .block{border:1px solid var(--border);border-radius:14px;overflow:hidden}
  .bh{padding:10px 12px 0;font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#98968E}
  .bb{padding:8px 12px 14px;font-family:var(--mono);font-size:12px}
  pre{margin:0;white-space:pre-wrap;word-break:break-word;max-height:280px;overflow:auto;background:#fafaf8;border-radius:8px;padding:8px}
  .yes{color:var(--yes);font-weight:700}.no{color:var(--no);font-weight:700}
  .big{font-size:34px;font-weight:700;font-family:var(--mono);margin:4px 0}
  .row{display:grid;grid-template-columns:70px 40px 1fr 120px;gap:8px;padding:5px 0;border-bottom:1px solid var(--border)}
  table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px}
  th,td{padding:5px 6px;border-bottom:1px solid var(--border);text-align:left}
  th{color:var(--muted);font-weight:600}
</style></head><body>
<div class="card">
  <header>
    <span class="brand">‖ BTC 15m Flow</span>
    <span class="chip">port 3001</span>
    <span class="chip" id="ticker">—</span>
    <span class="chip" id="mode">PAPER</span>
    <span class="spacer"></span>
    <a class="btn" href="http://127.0.0.1:3000/" target="_blank">Desk :3000</a>
    <a class="btn" href="http://127.0.0.1:3002/" target="_blank">Odds :3002</a>
  </header>
  <div class="grid">
    <section class="block">
      <div class="bh">Live market tape · Coinbase + Kalshi</div>
      <div class="bb">
        <div class="big" id="spot">—</div>
        <div id="delta">—</div>
        <table style="margin-top:10px">
          <tr><th>field</th><th>value</th></tr>
          <tr><td>window</td><td id="tWindow">—</td></tr>
          <tr><td>open</td><td id="tOpen">—</td></tr>
          <tr><td>YES ask</td><td id="tYes">—</td></tr>
          <tr><td>NO ask</td><td id="tNo">—</td></tr>
          <tr><td>YES mid</td><td id="tMid">—</td></tr>
          <tr><td>left</td><td id="tLeft">—</td></tr>
        </table>
      </div>
    </section>
    <section class="block">
      <div class="bh">Jev judgment · GET /jev</div>
      <div class="bb">
        <div class="big" id="side">—</div>
        <div id="meta">—</div>
        <pre id="jev">{}</pre>
        <div style="margin-top:8px"><a class="btn" href="/jev" target="_blank">open /jev</a>
        <a class="btn" href="#" id="forceJev">force re-judge</a></div>
      </div>
    </section>
    <section class="block" style="grid-column:1/-1">
      <div class="bh">Window decisions tape · last spins</div>
      <div class="bb" id="tape">—</div>
    </section>
  </div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=v=>v==null?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
const sec=s=>s==null?"—":(Math.floor(s/60)+":"+String(Math.round(s%60)).padStart(2,"0"));
async function tick(){
  try{
    const [j,m,d]=await Promise.all([
      fetch("/jev").then(r=>r.json()),
      fetch("/market").then(r=>r.json()),
      fetch("/decisions").then(r=>r.json()),
    ]);
    const w=j.window||m.window||{};
    const spot=j.spot||(m.spot&&m.spot.price);
    $("spot").textContent=fmt(spot);
    const delta=j.delta_from_open!=null?j.delta_from_open:w.delta_from_open;
    const dlt=$("delta");
    dlt.textContent=delta==null?"Δ —":("Δ "+(delta>=0?"+":"")+fmt(delta)+(j.delta_pct!=null||w.delta_pct!=null?" ("+Number(j.delta_pct!=null?j.delta_pct:w.delta_pct).toFixed(3)+"%)":""));
    dlt.className=delta==null?"":(delta>=0?"yes":"no");
    $("ticker").textContent=w.ticker||"KXBTC15M";
    $("tWindow").textContent=w.window_id||"—";
    $("tOpen").textContent=fmt(j.open_of_window!=null?j.open_of_window:w.open_of_window);
    $("tYes").textContent=fmt(j.window&&j.window.yes_ask||w.yes_ask);
    $("tNo").textContent=fmt(j.window&&j.window.no_ask||w.no_ask);
    $("tMid").textContent=fmt(j.yes_mid!=null?j.yes_mid:w.yes_mid);
    $("tLeft").textContent=sec(w.seconds_left);
    $("side").textContent=j.side||"WAIT";
    $("side").className="big "+(j.side==="YES"?"yes":j.side==="NO"?"no":"");
    $("meta").textContent=[j.trade_action,j.src,"conf "+(j.conf!=null?Number(j.conf).toFixed(2):"—"),j.reason].filter(Boolean).join(" · ");
    $("mode").textContent=j.liveArmed?"LIVE":"PAPER";
    $("jev").textContent=JSON.stringify(j,null,2);
    const rows=(d.tape||[]).slice(0,18).map(r=>{
      const side=r.side||"SKIP";
      return `<div class="row"><span>${(r.ts||"").slice(11,19)||"—"}</span><span class="${side==="YES"?"yes":side==="NO"?"no":""}">${side}</span><span>${r.result||"—"} · conf ${r.conf!=null?Number(r.conf).toFixed(2):"—"} · ${(r.judge&&r.judge.reason)||r.reason||""}</span><span>${r.ticker||"—"}</span></div>`;
    }).join("");
    $("tape").innerHTML=rows||"—";
  }catch(e){ $("meta").textContent="error "+e; }
}
$("forceJev").addEventListener("click",async e=>{e.preventDefault();await fetch("/jev?force=1");tick();});
tick(); setInterval(tick,2500);
</script></body></html>
"""


def serve_flow(host: str = "127.0.0.1", port: int = 3001) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), FlowHandler)


def main() -> None:
    server = serve_flow(config.host, 3001)
    print(f"[3001] flow desk  http://{config.host}:3001/  (also /jev /market /decisions)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
