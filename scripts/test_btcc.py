import ast
import sys
import time

sys.path.insert(0, r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot")
for p in [
    r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\app\btcc_knowledge.py",
    r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\app\judge.py",
    r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\app\risk_gate.py",
    r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\app\state.py",
]:
    ast.parse(open(p, encoding="utf-8").read())
    print("OK", p.split("\\")[-1])

from app.btcc_knowledge import DOCTRINE, btcc_signal_board, hygiene_flags, judgment_overlay_from_btcc

t0 = time.time()
b = btcc_signal_board()
print("board_ms", round((time.time() - t0) * 1000, 1))
print("lean", b.get("lean"), "setup", b.get("setup"), "conf", b.get("confidence"))
print("hurst", b.get("hurst"), "signals", b.get("signals"))
print("fibs keys", list((b.get("fibs") or {}).get("levels", {}).keys())[:8])
print("in_gp", (b.get("fibs") or {}).get("in_golden_pocket"), "edge", b.get("edge_vs_book"))
print("hygiene", b.get("hygiene"))
print("complete_set", b.get("complete_set"))
print("reasons", b.get("reasons"))
ovl = judgment_overlay_from_btcc(b)
print("overlay", {k: ovl.get(k) for k in ("lean", "conf", "hygiene_veto", "setup")})
print("doctrine rules", len(DOCTRINE["hard_rules"]))
