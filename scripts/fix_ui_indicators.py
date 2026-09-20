from pathlib import Path

p = Path(
    r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19"
    r"\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\app\ui.html"
)
text = p.read_text(encoding="utf-8")

# --- CSS for metric + mini graph + quality badge ---
css_add = """
    /* Metric indicator + mini graph */
    .m-ind {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .m-val {
      font-family: var(--font-mono);
      font-weight: 700;
      min-width: 48px;
    }
    .m-spark {
      width: 56px;
      height: 18px;
      border-radius: 4px;
      background: var(--track);
      vertical-align: middle;
    }
    .m-badge {
      font-family: var(--font-mono);
      font-size: 9px;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 4px;
      letter-spacing: 0.02em;
    }
    .m-badge.good { background: var(--yes-bar-dim); color: var(--yes-ink); }
    .m-badge.mid { background: var(--hold-cell); color: var(--late-ink); }
    .m-badge.bad { background: var(--no-bar-dim); color: var(--no-ink); }
    .m-badge.na { background: var(--panel); color: var(--muted); }
    .m-bar {
      width: 48px;
      height: 6px;
      background: var(--track);
      border-radius: 3px;
      overflow: hidden;
      display: inline-block;
    }
    .m-bar > i { display:block; height:100%; width:0; background: var(--badge-jev-fg); }
    .m-bar.good > i { background: var(--yes-bar); }
    .m-bar.bad > i { background: var(--no-bar); }
    .ind-row {
      display: grid;
      grid-template-columns: 110px 72px 56px 70px 1fr;
      gap: 6px;
      align-items: center;
      font-family: var(--font-mono);
      font-size: 11px;
      margin: 4px 0;
      padding: 4px 6px;
      border-radius: 8px;
      background: var(--panel);
    }
    .ind-row .name { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; }
    .ind-row .hint { color: var(--muted-2); font-size: 10px; }
"""

if "Metric indicator + mini graph" not in text:
    text = text.replace("    .route-SKIP { background: var(--hold-cell); color: var(--late-ink); }",
                        "    .route-SKIP { background: var(--hold-cell); color: var(--late-ink); }\n" + css_add)
    print("css added")

# --- Replace allInfoGrid content with indicator rows ---
old_strip_start = text.find('<div class="gates" id="allInfoGrid"')
old_strip_end = text.find('</div>\n        <div class="call-meta" id="aiReason"', old_strip_start)
if old_strip_start != -1 and old_strip_end != -1:
    new_grid = '''<div id="allInfoGrid" class="ind-grid" style="display:flex;flex-direction:column;gap:0">
          <div class="ind-row"><span class="name">Spot</span><span class="m-val" id="aiSpot">—</span><canvas class="m-spark" id="sp_spot" width="56" height="18"></canvas><span class="m-badge na" id="bd_spot">–</span><span class="hint" id="hint_spot">BTC last · trend for YES if rising</span></div>
          <div class="ind-row"><span class="name">Δ vs open</span><span class="m-val" id="aiDelta">—</span><canvas class="m-spark" id="sp_delta" width="56" height="18"></canvas><span class="m-badge na" id="bd_delta">–</span><span class="hint">+ favors YES · − favors NO</span></div>
          <div class="ind-row"><span class="name">Fair YES</span><span class="m-val" id="aiFair">—</span><canvas class="m-spark" id="sp_fair" width="56" height="18"></canvas><span class="m-badge na" id="bd_fair">–</span><span class="hint">model P(settle&gt;open) · high=YES</span></div>
          <div class="ind-row"><span class="name">Book YES</span><span class="m-val" id="aiYesMid">—</span><canvas class="m-spark" id="sp_book" width="56" height="18"></canvas><span class="m-badge na" id="bd_book">–</span><span class="hint">Kalshi mid · market price</span></div>
          <div class="ind-row"><span class="name">Edge fair−book</span><span class="m-val" id="aiEdge">—</span><canvas class="m-spark" id="sp_edge" width="56" height="18"></canvas><span class="m-badge na" id="bd_edge">–</span><span class="hint">+ lead YES · − lead NO · |&gt;0.08| strong</span></div>
          <div class="ind-row"><span class="name">YES / NO ask</span><span class="m-val" id="aiAsks">—</span><span class="m-bar" id="mb_ask"><i></i></span><span class="m-badge na" id="bd_ask">–</span><span class="hint">entry cost · lower ask = cheaper contract</span></div>
          <div class="ind-row"><span class="name">BTCC lean</span><span class="m-val" id="aiBtcc">—</span><span class="m-bar" id="mb_btcc"><i></i></span><span class="m-badge na" id="bd_btcc">–</span><span class="hint" id="hint_btcc">grokbot setup · fib+pocket+edge</span></div>
          <div class="ind-row"><span class="name">BTCC conf</span><span class="m-val" id="aiBConf">—</span><canvas class="m-spark" id="sp_bconf" width="56" height="18"></canvas><span class="m-badge na" id="bd_bconf">–</span><span class="hint">≥0.55 tradable in recover mode</span></div>
          <div class="ind-row"><span class="name">Hurst H</span><span class="m-val" id="aiHurst">—</span><canvas class="m-spark" id="sp_hurst" width="56" height="18"></canvas><span class="m-badge na" id="bd_hurst">–</span><span class="hint">&gt;0.55 trend · &lt;0.45 fade · ~0.5 no edge</span></div>
          <div class="ind-row"><span class="name">QD lean</span><span class="m-val" id="aiQd">—</span><span class="m-bar" id="mb_qd"><i></i></span><span class="m-badge na" id="bd_qd">–</span><span class="hint">QuantDinger BTC composite</span></div>
          <div class="ind-row"><span class="name">QD edge</span><span class="m-val" id="aiQdEdge">—</span><canvas class="m-spark" id="sp_qde" width="56" height="18"></canvas><span class="m-badge na" id="bd_qde">–</span><span class="hint">same as fair−book from QD pack</span></div>
          <div class="ind-row"><span class="name">Judge</span><span class="m-val" id="aiJudge">—</span><span class="m-bar" id="mb_judge"><i></i></span><span class="m-badge na" id="bd_judge">–</span><span class="hint" id="hint_judge">src+side after risk/QD/BTCC</span></div>
          <div class="ind-row"><span class="name">Judge conf</span><span class="m-val" id="aiJConf">—</span><canvas class="m-spark" id="sp_jconf" width="56" height="18"></canvas><span class="m-badge na" id="bd_jconf">–</span><span class="hint">≥ conf_floor (0.45) to fire</span></div>
          <div class="ind-row"><span class="name">Route / Risk</span><span class="m-val" id="aiRisk">—</span><span class="m-bar" id="mb_risk"><i></i></span><span class="m-badge na" id="bd_risk">–</span><span class="hint">ANY fail = no trade</span></div>
          <div class="ind-row"><span class="name">Hygiene</span><span class="m-val" id="aiHyg">—</span><span class="m-bar" id="mb_hyg"><i></i></span><span class="m-badge na" id="bd_hyg">–</span><span class="hint">override OFF = always green</span></div>
          <div class="ind-row"><span class="name">Book / spot ms</span><span class="m-val" id="aiLat">—</span><canvas class="m-spark" id="sp_lat" width="56" height="18"></canvas><span class="m-badge na" id="bd_lat">–</span><span class="hint">lower = faster edge vs Kalshi print</span></div>
          <div class="ind-row"><span class="name">Quant n / hit</span><span class="m-val" id="aiQN">—</span><canvas class="m-spark" id="sp_hit" width="56" height="18"></canvas><span class="m-badge na" id="bd_hit">–</span><span class="hint" id="hint_q">sample size + hit rate vs luck band</span></div>
          <div class="ind-row"><span class="name">Brier</span><span class="m-val" id="aiQBrier">—</span><span class="m-bar" id="mb_brier"><i></i></span><span class="m-badge na" id="bd_brier">–</span><span class="hint">≤0.25 calibrated · lower better</span></div>
          <div class="ind-row"><span class="name">Secs left</span><span class="m-val" id="aiSecs">—</span><canvas class="m-spark" id="sp_secs" width="56" height="18"></canvas><span class="m-badge na" id="bd_secs">–</span><span class="hint">too late + weak = skip stale window</span></div>
          <div class="ind-row"><span class="name">DECISION GATE</span><span class="m-val" id="aiGate">—</span><span class="m-bar" id="mb_gate"><i></i></span><span class="m-badge na" id="bd_gate">–</span><span class="hint" id="hint_gate">aggregate: how good is state to trade</span></div>
        </div>
'''
    text = text[:old_strip_start] + new_grid + text[old_strip_end:]
    print("grid replaced with indicator rows")
else:
    print("WARN could not find allInfoGrid bounds", old_strip_start, old_strip_end)

# --- JS: history + spark + quality scoring + fill ---
js_mod = r"""
    // ===== Metric indicators: history + mini graphs + quality =====
    const METRIC_HIST = {
      spot: [], delta: [], fair: [], book: [], edge: [], bconf: [], hurst: [],
      qde: [], jconf: [], lat: [], hit: [], secs: []
    };
    const HIST_MAX = 48;

    function pushHist(key, v) {
      if (v == null || Number.isNaN(Number(v))) return;
      const a = METRIC_HIST[key] || (METRIC_HIST[key] = []);
      a.push(Number(v));
      if (a.length > HIST_MAX) a.shift();
    }

    function drawSpark(canvasId, key, color) {
      const c = document.getElementById(canvasId);
      if (!c) return;
      const ctx = c.getContext("2d");
      const W = c.width, H = c.height;
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "#F1F0EC";
      ctx.fillRect(0, 0, W, H);
      const a = METRIC_HIST[key] || [];
      if (a.length < 2) {
        ctx.fillStyle = "#98968E";
        ctx.font = "8px monospace";
        ctx.fillText("…", 22, 12);
        return;
      }
      let mn = Math.min(...a), mx = Math.max(...a);
      if (mx - mn < 1e-9) { mx = mn + 1; }
      ctx.strokeStyle = color || "#4C3EBB";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      a.forEach((v, i) => {
        const x = (i / (a.length - 1)) * (W - 2) + 1;
        const y = H - 2 - ((v - mn) / (mx - mn)) * (H - 4);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      const last = a[a.length - 1];
      const lx = W - 1, ly = H - 2 - ((last - mn) / (mx - mn)) * (H - 4);
      ctx.fillStyle = color || "#4C3EBB";
      ctx.beginPath(); ctx.arc(lx - 2, ly, 2, 0, Math.PI * 2); ctx.fill();
    }

    function setBadge(id, score, label) {
      const el = document.getElementById(id);
      if (!el) return;
      const s = score == null ? null : Number(score);
      let cls = "na", txt = label || "–";
      if (s != null) {
        if (s >= 0.67) { cls = "good"; txt = (label || "GOOD") + " ▲"; }
        else if (s >= 0.4) { cls = "mid"; txt = (label || "MID") + " –"; }
        else { cls = "bad"; txt = (label || "BAD") + " ▼"; }
      }
      el.className = "m-badge " + cls;
      el.textContent = txt;
    }

    function setBar(id, score, invert) {
      const wrap = document.getElementById(id);
      if (!wrap) return;
      const i = wrap.querySelector("i");
      let s = score == null ? 0 : Math.max(0, Math.min(1, Number(score)));
      if (invert) s = 1 - s;
      if (i) i.style.width = (s * 100).toFixed(0) + "%";
      wrap.className = "m-bar " + (s >= 0.67 ? "good" : s < 0.4 ? "bad" : "");
    }

    // Quality scores 0..1 for "how good for OUR 15m decision"
    function scoreSpotTrend(delta) {
      if (delta == null) return null;
      return 0.5 + Math.max(-0.5, Math.min(0.5, Number(delta) / 80));
    }
    function scoreFair(f) {
      if (f == null) return null;
      // distance from 0.5 = conviction either way
      return Math.abs(Number(f) - 0.5) * 2;
    }
    function scoreEdge(e) {
      if (e == null) return null;
      return Math.min(1, Math.abs(Number(e)) / 0.25);
    }
    function scoreConf(c) {
      if (c == null) return null;
      return Number(c);
    }
    function scoreHurst(h) {
      if (h == null) return null;
      if (h > 0.55 || h < 0.45) return Math.min(1, Math.abs(h - 0.5) * 4 + 0.4);
      return 0.35; // random — weak for decision
    }
    function scoreLat(ms) {
      if (ms == null) return null;
      const v = Number(ms);
      if (v <= 60) return 1;
      if (v <= 120) return 0.75;
      if (v <= 250) return 0.5;
      return 0.25;
    }
    function scoreBrier(b) {
      if (b == null) return null;
      return Math.max(0, Math.min(1, 1 - Number(b) / 0.5));
    }
    function scoreHit(h, n) {
      if (h == null || !n) return null;
      // good if hit rate far from 0.5 with enough n
      const strength = Math.min(1, n / 50);
      return Math.max(0, Math.min(1, Math.abs(Number(h) - 0.5) * 2 * 0.6 + strength * 0.4));
    }
    function scoreLeanSide(lean, conf, fair, edge) {
      if (lean !== "YES" && lean !== "NO") return 0.15;
      const c = Number(conf || 0);
      const e = Math.abs(Number(edge || 0));
      const agree = (lean === "YES" && Number(fair || 0.5) >= 0.5) || (lean === "NO" && Number(fair || 0.5) < 0.5);
      return Math.max(0, Math.min(1, c * 0.5 + Math.min(1, e / 0.2) * 0.3 + (agree ? 0.2 : 0)));
    }

    function renderAllIndicators(s, latest, dec, win, spot, ff, qdModels, qdDec, lastJ, meta) {
      const b = s.btcc || {};
      const hy = b.hygiene || {};
      const q = s.quant || {};
      const rk = latest.risk_gate || (lastJ && lastJ.risk) || {};
      const setText2 = (id, v) => { const n = document.getElementById(id); if (n) n.textContent = (v == null || v === "" ? "—" : v); };

      const fair = ff.fair_yes != null ? ff.fair_yes : qdModels.fair_yes;
      const edge = ff.edge_vs_book != null ? ff.edge_vs_book : qdModels.edge_vs_book;
      const book = win.yes_mid != null ? win.yes_mid : qdModels.book_yes;
      const deltaPct = (spot != null && win.open_of_window) ? (Number(spot) - Number(win.open_of_window)) : null;
      const lat = Math.max(Number(ff.book_ms || 999), Number(ff.spot_ms || 999));

      pushHist("spot", spot);
      pushHist("delta", deltaPct);
      pushHist("fair", fair);
      pushHist("book", book);
      pushHist("edge", edge);
      pushHist("bconf", b.confidence);
      pushHist("hurst", b.hurst);
      pushHist("qde", qdModels.edge_vs_book);
      pushHist("jconf", dec.conf);
      pushHist("lat", lat < 900 ? lat : null);
      pushHist("hit", q.hit_rate);
      pushHist("secs", win.seconds_left);

      setText2("aiSpot", spot != null ? Number(spot).toLocaleString(undefined, {maximumFractionDigits:0}) : "—");
      setText2("aiDelta", deltaPct != null ? deltaPct.toFixed(2) + "¢" : "—");
      setText2("aiFair", fair != null ? Number(fair).toFixed(3) : "—");
      setText2("aiBook", book != null ? Number(book).toFixed(3) : "—");
      setText2("aiEdge", edge != null ? Number(edge).toFixed(3) : "—");
      setText2("aiAsks", (win.yes_ask != null ? "Y" + Number(win.yes_ask).toFixed(2) : "Y—") + " / " + (win.no_ask != null ? "N" + Number(win.no_ask).toFixed(2) : "N—"));
      setText2("aiBtcc", b.lean || "—");
      setText2("aiBConf", b.confidence != null ? Number(b.confidence).toFixed(2) : "—");
      setText2("aiHurst", b.hurst != null ? Number(b.hurst).toFixed(3) : "—");
      setText2("aiQd", qdDec.lean || "—");
      setText2("aiQdEdge", qdModels.edge_vs_book != null ? Number(qdModels.edge_vs_book).toFixed(3) : "—");
      setText2("aiJudge", ((dec.judge_src || "") + " " + (dec.side || lastJ && lastJ.side || "")).trim() || "—");
      setText2("aiJConf", dec.conf != null ? Number(dec.conf).toFixed(2) : "—");
      const route = dec.route || lastJ && lastJ.route || "—";
      setText2("aiRisk", (rk.verdict || (rk.blocked ? "BLOCK" : rk.passed ? "ALLOW" : "—")) + " · " + route);
      setText2("aiHyg", hy.override ? "OFF (override)" : hy.veto ? "VETO" : "clear");
      setText2("aiLat", (ff.book_ms != null ? ff.book_ms : "—") + " / " + (ff.spot_ms != null ? ff.spot_ms : "—") + "ms");
      setText2("aiQN", (q.sample_n_judgments != null ? q.sample_n_judgments : "—") + " · " + (q.hit_rate != null ? (Number(q.hit_rate)*100).toFixed(0)+"%" : "—"));
      setText2("aiQBrier", q.calibration && q.calibration.brier != null ? Number(q.calibration.brier).toFixed(3) : "—");
      setText2("aiSecs", win.seconds_left != null ? fmtSec(win.seconds_left) : "—");

      // quality badges
      const scSpot = scoreSpotTrend(deltaPct);
      setBadge("bd_spot", scSpot, scSpot == null ? "n/a" : scSpot >= 0.6 ? "up=YES" : scSpot <= 0.4 ? "down=NO" : "flat");
      setBadge("bd_delta", scSpot, scSpot == null ? "n/a" : deltaPct > 0 ? "YES-side" : deltaPct < 0 ? "NO-side" : "flat");
      const scFair = scoreFair(fair);
      setBadge("bd_fair", fair == null ? null : (fair >= 0.5 ? scFair * 0.3 + 0.7 : scFair * 0.3 + 0.7),
        fair == null ? "n/a" : (fair >= 0.55 ? "YES lean" : fair <= 0.45 ? "NO lean" : "unclear"));
      const scBook = fair != null && book != null ? null : null;
      setBadge("bd_book", book == null ? null : Math.abs(book - 0.5) * 2 * 0.5 + 0.3,
        book == null ? "n/a" : (book >= 0.55 ? "mkt YES" : book <= 0.45 ? "mkt NO" : "mkt mid"));
      const scEdge = scoreEdge(edge);
      setBadge("bd_edge", scEdge, edge == null ? "n/a" : (Math.abs(edge) >= 0.08 ? (edge > 0 ? "YES lead" : "NO lead") : "weak edge"));
      const cheap = win.yes_ask != null ? Math.max(0, 1 - Number(win.yes_ask)) : null;
      setBadge("bd_ask", cheap, cheap == null ? "n/a" : (Number(win.yes_ask) <= 0.15 ? "cheap YES" : Number(win.no_ask) <= 0.15 ? "cheap NO" : "pricey"));
      setBar("mb_ask", cheap);
      const scBtcc = scoreLeanSide(b.lean, b.confidence, fair, edge);
      setBadge("bd_btcc", scBtcc, b.setup || "–");
      setBar("mb_btcc", scBtcc);
      const scBC = scoreConf(b.confidence);
      setBadge("bd_bconf", scBC, b.confidence != null && b.confidence >= 0.55 ? "tradable" : b.confidence != null ? "weak" : "n/a");
      const scH = scoreHurst(b.hurst);
      setBadge("bd_hurst", scH, b.hurst == null ? "n/a" : (b.hurst > 0.55 ? "trend" : b.hurst < 0.45 ? "mean-rev" : "random"));
      const scQd = scoreLeanSide(qdDec.lean, qdDec.conf, qdModels.fair_yes, qdModels.edge_vs_book);
      setBadge("bd_qd", scQd, qdDec.lean || "–");
      setBar("mb_qd", scQd);
      const scQe = scoreEdge(qdModels.edge_vs_book);
      setBadge("bd_qde", scQe, qdModels.edge_vs_book == null ? "n/a" : (Math.abs(qdModels.edge_vs_book) >= 0.08 ? "strong" : "weak"));
      const jLean = dec.side || (lastJ && lastJ.side);
      const scJ = scoreLeanSide(jLean, dec.conf, fair, edge);
      setBadge("bd_judge", scJ, (jLean || "–") + (dec.judge_src ? " " + String(dec.judge_src).slice(0, 8) : ""));
      setBar("mb_judge", scJ);
      const scJC = scoreConf(dec.conf);
      setBadge("bd_jconf", scJC, dec.conf == null ? "n/a" : dec.conf >= (g_conf_floor || 0.45) ? "above floor" : "below floor");
      const riskOk = !rk.blocked && (rk.verdict === "ALLOW" || rk.passed === true);
      const scR = riskOk ? 1 : 0;
      setBadge("bd_risk", scR, riskOk ? "OPEN" : "BLOCKED");
      setBar("mb_risk", scR);
      const scH2 = hy.veto && !hy.override ? 0 : 1;
      setBadge("bd_hyg", scH2, hy.override ? "nix'd" : hy.veto ? "veto" : "clear");
      setBar("mb_hyg", scH2);
      const scL = scoreLat(lat);
      setBadge("bd_lat", scL, scL == null ? "n/a" : scL >= 0.75 ? "fast" : scL >= 0.5 ? "ok" : "slow");
      const scHit = scoreHit(q.hit_rate, q.sample_n_judgments);
      setBadge("bd_hit", scHit, q.sample_n_judgments != null && q.sample_n_judgments >= 30 ? "sample ok" : "thin n");
      const scB = scoreBrier(q.calibration && q.calibration.brier);
      setBadge("bd_brier", scB, scB == null ? "n/a" : scB >= 0.67 ? "calibrated" : "uncal");
      const secs = win.seconds_left;
      const scSecs = secs == null ? null : (secs > 60 ? 1 : secs > 20 ? 0.6 : 0.2);
      setBadge("bd_secs", scSecs, secs == null ? "n/a" : secs > 60 ? "fresh" : secs > 20 ? "closing" : "stale");
      drawSpark("sp_spot", "spot", "#0FA968");
      drawSpark("sp_delta", "delta", "#4C3EBB");
      drawSpark("sp_fair", "fair", "#4C3EBB");
      drawSpark("sp_book", "book", "#E4573D");
      drawSpark("sp_edge", "edge", "#C98A1B");
      drawSpark("sp_bconf", "bconf", "#4C3EBB");
      drawSpark("sp_hurst", "hurst", "#C98A1B");
      drawSpark("sp_qde", "qde", "#0FA968");
      drawSpark("sp_jconf", "jconf", "#4C3EBB");
      drawSpark("sp_lat", "lat", "#E4573D");
      drawSpark("sp_hit", "hit", "#0FA968");
      drawSpark("sp_secs", "secs", "#77776F");

      // Aggregate DECISION GATE score
      const parts = [scSpot, scFair, scEdge, scBtcc, scQd, scJ, scR, scH2, scL].filter((x) => x != null);
      const gate = parts.length ? parts.reduce((a, c) => a + c, 0) / parts.length : null;
      setText2("aiGate", gate != null ? gate.toFixed(2) : "—");
      setBar("mb_gate", gate);
      setBadge("bd_gate", gate,
        gate == null ? "n/a"
        : riskOk && gate >= 0.67 ? "TRADE-ISH"
        : !riskOk ? "NO-TRADE"
        : gate >= 0.5 ? "MARGINAL"
        : "WAIT");
      setText2("hint_gate", gate == null ? "waiting…" :
        (riskOk ? "aggregate quality for 15m YES/NO" : "risk blocked — do not fire"));
    }

"""

if "renderAllIndicators" not in text:
    needle = "    function renderBTCC(s) {"
    if needle in text:
        text = text.replace(needle, js_mod + "\n" + needle, 1)
        print("injected indicator engine")
    else:
        needle2 = "    async function load() {"
        text = text.replace(needle2, js_mod + "\n" + needle2, 1)
        print("injected indicator engine before load")

# Replace old allInfo fill call with renderAllIndicators
old_fill_marker = '// ALL LIVE INFO strip'
if old_fill_marker in text:
    start = text.find(old_fill_marker)
    # find end of that try block roughly - next "renderTape"
    end = text.find("renderTape(s.events, s.last_spin);", start)
    if end != -1:
        new_call = """      try {
        const ff2 = ff || {};
        renderAllIndicators(s, latest, dec, win, spot, ff2, qdModels, qdDec, lastJ, meta);
      } catch (e) { console.warn("indicators", e); }
      setText2_keep_reason(); function setText2_keep_reason() {}
      try {
        const n = document.getElementById("aiReason");
        if (n) n.textContent = [
          dec.reason || "",
          s.btcc && s.btcc.reason ? "BTCC:" + s.btcc.reason : "",
          (s.quantdinger && s.quantdinger.btc && s.quantdinger.btc.decision && s.quantdinger.btc.decision.reason) ? "QD:" + s.quantdinger.btc.decision.reason : "",
        ].filter(Boolean).join("  ||  ") || "—";
      } catch (e) {}
      """
        text = text[:start] + new_call + text[end:]
        print("replaced allInfo fill with indicator renderer")

# g_conf_floor - inject from gates in render - add var at top of renderAllIndicators usage
if "const g_conf_floor" not in text:
    text = text.replace(
        "function renderAllIndicators(s, latest, dec, win, spot, ff, qdModels, qdDec, lastJ, meta) {",
        "function renderAllIndicators(s, latest, dec, win, spot, ff, qdModels, qdDec, lastJ, meta) {\n      const g_conf_floor = ((latest && latest.gates && latest.gates.conf_floor) != null) ? latest.gates.conf_floor : 0.45;",
        1,
    )
    print("conf floor injected")

# Ensure aiOpen / other ids that might be referenced still exist - aiYesMid used
if 'id="aiOpen"' not in text:
    # spot row has open - add open to first row hint via delta only - add aiOpen cell in spot row
    text = text.replace(
        '<span class="m-val" id="aiSpot">—</span>',
        '<span class="m-val" id="aiSpot">—</span>',
    )

p.write_text(text, encoding="utf-8")
print("bytes", len(text.encode("utf-8")))
print("indicators", "renderAllIndicators" in text)
print("spark css", ".m-spark" in text)
print("ind rows", text.count('class="ind-row"'))
