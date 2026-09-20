from pathlib import Path
import re

p = Path(
    r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19"
    r"\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\app\ui.html"
)
text = p.read_text(encoding="utf-8")

# 1) Default all panels visible — user wants EVERYTHING on the page
# Replace tab CSS so panels stack (all shown) and tabs jump-scroll
old_tab_css_start = text.find("    /* Tabs */")
if old_tab_css_start == -1:
    print("tab css not found")
else:
    # find next section after tab-wrap media query - we'll patch key rules
    text = text.replace(
        """    .tab-panel {
      display: none;
      flex: 1;
      min-height: 0;
      overflow: auto;
      padding: 14px 20px 18px;
      gap: 12px;
    }
    .tab-panel.active {
      display: grid;
    }""",
        """    .tab-panel {
      display: grid;
      flex: none;
      min-height: 0;
      overflow: visible;
      padding: 14px 20px 18px;
      gap: 12px;
      margin-bottom: 8px;
      border-bottom: 1px dashed var(--border);
    }
    .tab-panel.active {
      display: grid;
    }
    /* ALL panels always on — user wants full desk visible */
    .tab-wrap {
      overflow: auto;
      padding-bottom: 24px;
    }""",
    )
    print("tab panels now always visible")

# 2) Ensure grid layouts apply to all sections not just .active
for sec in ["tab-desk", "tab-charts", "tab-quant"]:
    text = text.replace(f"#{sec}.active {{", f"#{sec}, #{sec}.active {{")
text = text.replace("#tab-pipeline.active {", "#tab-pipeline, #tab-pipeline.active {")
text = text.replace("#tab-tape.active {", "#tab-tape, #tab-tape.active {")
text = text.replace("#tab-btcc.active {", "#tab-btcc, #tab-btcc.active {")

# 3) Tab buttons become jump links — still "click to see different things"
text = text.replace(
    """      btns.forEach((b) => {
        b.addEventListener("click", () => {
          const id = b.dataset.tab;
          btns.forEach((x) => x.classList.remove("active"));
          panels.forEach((p) => p.classList.remove("active"));
          b.classList.add("active");
          const panel = document.getElementById("tab-" + id);
          if (panel) panel.classList.add("active");
          try { localStorage.setItem("deskTab", id); } catch (e) {}
          if (typeof load === "function") load();
        });
      });""",
    """      btns.forEach((b) => {
        b.addEventListener("click", () => {
          const id = b.dataset.tab;
          btns.forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          // keep ALL panels visible; scroll to the clicked one
          const panel = document.getElementById("tab-" + id);
          if (panel) {
            panel.classList.add("active");
            panel.scrollIntoView({ behavior: "smooth", block: "start" });
          }
          try { localStorage.setItem("deskTab", id); } catch (e) {}
          if (typeof load === "function") load();
        });
      });""",
)
print("tabs now scroll-to-section")

# 4) Inject "ALL INFO" mega strip under stats — live dump of every key number
if "id=\"allInfoStrip\"" not in text:
    mega = """
    <div id="allInfoStrip" class="block" style="margin:8px 20px 0">
      <div class="block-head">ALL LIVE INFO · every panel feed</div>
      <div class="block-body">
        <div class="gates" id="allInfoGrid" style="grid-template-columns:1fr 1fr 1fr">
          <span>spot <b id="aiSpot">—</b></span>
          <span>open <b id="aiOpen">—</b></span>
          <span>Δ <b id="aiDelta">—</b></span>
          <span>YES mid <b id="aiYesMid">—</b></span>
          <span>YES ask <b id="aiYesAsk">—</b></span>
          <span>NO ask <b id="aiNoAsk">—</b></span>
          <span>fair YES <b id="aiFair">—</b></span>
          <span>edge <b id="aiEdge">—</b></span>
          <span>book ms <b id="aiBookMs">—</b></span>
          <span>spot ms <b id="aiSpotMs">—</b></span>
          <span>chart pts <b id="aiPts">—</b></span>
          <span>conn <b id="aiConn">—</b></span>
          <span>judge <b id="aiJudge">—</b></span>
          <span>judge conf <b id="aiJConf">—</b></span>
          <span>route <b id="aiRoute">—</b></span>
          <span>BTCC lean <b id="aiBtcc">—</b></span>
          <span>BTCC setup <b id="aiBSetup">—</b></span>
          <span>Hurst <b id="aiHurst">—</b></span>
          <span>QD lean <b id="aiQd">—</b></span>
          <span>QD edge <b id="aiQdEdge">—</b></span>
          <span>quant n <b id="aiQN">—</b></span>
          <span>hit rate <b id="aiQHit">—</b></span>
          <span>brier <b id="aiQBrier">—</b></span>
          <span>risk <b id="aiRisk">—</b></span>
          <span>hygiene <b id="aiHyg">—</b></span>
          <span>mode <b id="aiMode">—</b></span>
          <span>target <b id="aiTarget">$6</b></span>
          <span>last print <b id="aiPrint">—</b></span>
          <span>ticker <b id="aiTicker">—</b></span>
          <span>secs <b id="aiSecs">—</b></span>
        </div>
        <div class="call-meta" id="aiReason" style="margin-top:8px">—</div>
      </div>
    </div>
"""
    # insert after stats closing div
    needle = """      <span>uptime <strong id="uptime">00:00:00</strong></span>
    </div>
"""
    if needle in text:
        text = text.replace(needle, needle + mega, 1)
        print("injected allInfoStrip")
    else:
        print("WARN stats block not found for mega strip")

# 5) Update render() to fill allInfoStrip
if "aiSpot" in text and "allInfoGrid" in text:
    fill = r"""
      // ALL LIVE INFO strip
      try {
        const setText2 = (id, v) => { const n = document.getElementById(id); if (n) n.textContent = (v == null || v === "" ? "—" : v); };
        setText2("aiSpot", fmtPx(spot));
        setText2("aiOpen", fmtPx(win.open_of_window));
        setText2("aiDelta", deltaTxt);
        setText2("aiYesMid", win.yes_mid != null ? Number(win.yes_mid).toFixed(3) : "—");
        setText2("aiYesAsk", win.yes_ask != null ? Number(win.yes_ask).toFixed(3) : "—");
        setText2("aiNoAsk", win.no_ask != null ? Number(win.no_ask).toFixed(3) : "—");
        setText2("aiFair", ff.fair_yes != null ? Number(ff.fair_yes).toFixed(3) : ((s.quantdinger && s.quantdinger.btc && s.quantdinger.btc.models && s.quantdinger.btc.models.fair_yes) != null ? Number(s.quantdinger.btc.models.fair_yes).toFixed(3) : "—"));
        setText2("aiEdge", ff.edge_vs_book != null ? Number(ff.edge_vs_book).toFixed(3) : "—");
        setText2("aiBookMs", ff.book_ms != null ? ff.book_ms + "ms" : "—");
        setText2("aiSpotMs", ff.spot_ms != null ? ff.spot_ms + "ms" : "—");
        setText2("aiPts", (s.charts && s.charts.spot && s.charts.spot.length) || 0);
        setText2("aiConn", s.connection || "—");
        setText2("aiJudge", dec.judge_src || "—");
        setText2("aiJConf", conf != null ? Number(conf).toFixed(2) : "—");
        setText2("aiRoute", dec.route || "—");
        setText2("aiBtcc", (s.btcc && s.btcc.lean) || "—");
        setText2("aiBSetup", (s.btcc && s.btcc.setup) || "—");
        setText2("aiHurst", (s.btcc && s.btcc.hurst != null) ? s.btcc.hurst : "—");
        setText2("aiQd", qdDec.lean || "—");
        setText2("aiQdEdge", (qdModels.edge_vs_book != null) ? Number(qdModels.edge_vs_book).toFixed(3) : "—");
        setText2("aiQN", (s.quant && s.quant.sample_n_judgments) != null ? s.quant.sample_n_judgments : "—");
        setText2("aiQHit", (s.quant && s.quant.hit_rate != null) ? (Number(s.quant.hit_rate)*100).toFixed(1)+"%" : "—");
        setText2("aiQBrier", (s.quant && s.quant.calibration && s.quant.calibration.brier != null) ? Number(s.quant.calibration.brier).toFixed(3) : "—");
        const rk = latest.risk_gate || (lastJ && lastJ.risk) || {};
        setText2("aiRisk", rk.verdict || (rk.blocked ? "BLOCK" : rk.passed ? "ALLOW" : "—"));
        setText2("aiHyg", (s.btcc && s.btcc.hygiene) ? ((s.btcc.hygiene.override ? "OFF/override" : s.btcc.hygiene.veto ? "VETO" : "clear")) : "—");
        setText2("aiMode", meta.liveTrading ? "LIVE" : "PAPER");
        setText2("aiTarget", "$" + Number((s.btcc && s.btcc.recover_target_usd) || meta.martingaleTarget || 6).toFixed(0));
        setText2("aiPrint", ff.last_print ? (Number(ff.last_print.yes||0).toFixed(2) + " @" + String(ff.last_print.ts||"").slice(11,19)) : "—");
        setText2("aiTicker", mf.ticker || win.ticker || "—");
        setText2("aiSecs", win.seconds_left != null ? fmtSec(win.seconds_left) : "—");
        setText2("aiReason", [
          dec.reason || "",
          s.btcc && s.btcc.reason ? "BTCC:" + s.btcc.reason : "",
          s.quantdinger && s.quantdinger.btc && s.quantdinger.btc.decision && s.quantdinger.btc.decision.reason ? "QD:" + s.quantdinger.btc.decision.reason : "",
        ].filter(Boolean).join("  ||  ") || "—");
      } catch (e) { console.warn("allInfo", e); }
"""
    # insert before renderTape call in render
    if "setText2(\"aiSpot\"" not in text:
        text = text.replace(
            "      renderTape(s.events, s.last_spin);\n    }",
            fill + "\n      renderTape(s.events, lastJ || s.last_spin);\n    }",
            1,
        )
        # fix - renderTape should stay s.last_spin
        text = text.replace("renderTape(s.events, lastJ || s.last_spin);", "renderTape(s.events, s.last_spin);")
        print("wired allInfo fill")

p.write_text(text, encoding="utf-8")
print("ui bytes", len(text.encode("utf-8")))
print("allInfoStrip", 'id="allInfoStrip"' in text)
print("panels visible css", "keep ALL panels" in text or "display: grid;\n      flex: none" in text)
