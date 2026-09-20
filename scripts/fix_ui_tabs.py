from pathlib import Path

p = Path(
    r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19"
    r"\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\app\ui.html"
)
text = p.read_text(encoding="utf-8")
marker = "    const $ = (id) => document.getElementById(id);"
first = text.find(marker)
second = text.find(marker, first + 5) if first >= 0 else -1
print("first", first, "second", second)
if first >= 0 and second > first:
    # if between first+marker and second there is raw HTML, strip it
    between = text[first + len(marker) : second]
    if "<div" in between or "<aside" in between:
        text = text[: first + len(marker)] + "\n" + text[second:]
        print("stripped orphan HTML", len(between), "chars")
# collapse duplicate const $
text = text.replace(marker + "\n" + marker, marker)

if "function renderBTCC" not in text:
    btcc_fn = """
    function renderBTCC(s) {
      const b = s.btcc || {};
      const hy = b.hygiene || {};
      const fibs = b.fibs || {};
      const lv = fibs.levels || {};
      const lean = b.lean || "—";
      const el = $("btccLean");
      if (el && el.childNodes[0]) {
        el.childNodes[0].nodeValue = lean;
        const pc = $("btccConf");
        if (pc) pc.textContent = b.confidence != null ? " @ " + Number(b.confidence).toFixed(2) : "";
        el.style.color = lean === "YES" ? "var(--yes-ink)" : lean === "NO" ? "var(--no-ink)" : "var(--late-ink)";
      }
      const setText = (id, v) => { const n = $(id); if (n) n.textContent = (v == null || v === "") ? "—" : v; };
      setText("btccSetup", b.setup);
      setText("btccSetupVal", b.setup);
      setText("btccHurst", b.hurst != null ? Number(b.hurst).toFixed(3) : "—");
      setText("btccGp", fibs.in_golden_pocket ? "YES" : "no");
      setText("btccReclaim", lv.reclaim != null ? Number(lv.reclaim).toLocaleString(undefined, {maximumFractionDigits: 0}) : "—");
      setText("btccFlush", lv.flush != null ? Number(lv.flush).toLocaleString(undefined, {maximumFractionDigits: 0}) : "—");
      setText("btccFair", b.fair_yes != null ? Number(b.fair_yes).toFixed(3) : "—");
      setText("btccEdge", b.edge_vs_book != null ? (Number(b.edge_vs_book) >= 0 ? "+" : "") + Number(b.edge_vs_book).toFixed(3) : "—");
      setText("btccScore", b.confluence_score != null ? Number(b.confluence_score).toFixed(3) : "—");
      setText("btccHygiene", hy.veto ? ("VETO " + (hy.flags || []).join(",")) : "clear");
      const cs = b.complete_set || {};
      setText("btccCset", cs.flagged ? ("GAP sum=" + cs.sum) : (cs.sum != null ? "ok sum=" + cs.sum : "—"));
      setText("btccReasons", (b.reasons || []).join(" · "));
      setText("btccSignals", (b.signals || []).join(", "));
      const fibBox = $("btccFibs");
      if (fibBox) {
        fibBox.innerHTML = Object.keys(lv).length
          ? Object.entries(lv).map(function (kv) {
              const k = kv[0], v = kv[1];
              const val = Array.isArray(v)
                ? v.map(function (x) { return Number(x).toLocaleString(undefined, {maximumFractionDigits: 0}); }).join(" – ")
                : (typeof v === "number" ? Number(v).toLocaleString(undefined, {maximumFractionDigits: 0}) : String(v));
              return '<div class="model-row"><span>' + k + '</span><div class="lad-bar"><i style="width:40%;background:#4C3EBB"></i></div><span>' + val + '</span></div>';
            }).join("")
          : "—";
      }
      const doc = $("btccDoctrine");
      const rules = (b.doctrine && b.doctrine.hard_rules) || (s.btcc && s.btcc.doctrine && s.btcc.doctrine.hard_rules) || [];
      if (doc && rules.length) {
        doc.innerHTML = rules.map(function (r) {
          return '<div class="risk-item pass"><span>✓</span><span>rule</span><span>' + r + '</span></div>';
        }).join("");
      }
      const kill = (b.doctrine && b.doctrine.kill_list) || [];
      setText("btccKill", kill.length ? "kill list: " + kill.join(" · ") : "");
    }
"""
    needle = "    async function load() {"
    if needle in text:
        text = text.replace(needle, btcc_fn + "\n" + needle, 1)
        print("injected renderBTCC")
    else:
        print("WARN no load()")

if 'safe(() => renderBTCC(s), "btcc");' not in text:
    old = 'safe(() => renderModelBars(s, latest, dec, lastJ), "models");'
    if old in text:
        text = text.replace(old, old + '\n      safe(() => renderBTCC(s), "btcc");', 1)
        print("wired renderBTCC")

p.write_text(text, encoding="utf-8")
print("bytes", len(text.encode("utf-8")))
print("const$ count", text.count(marker))
print("tabs", 'data-tab="btcc"' in text)
print("renderBTCC", "function renderBTCC" in text)
print("wired", 'renderBTCC(s), "btcc"' in text)
