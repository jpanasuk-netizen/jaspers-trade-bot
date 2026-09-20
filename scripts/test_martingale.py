import sys, os, json
root = r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot"
sys.path.insert(0, root)
os.chdir(root)
for m in list(sys.modules):
    if m.startswith("app."):
        del sys.modules[m]
from app.config import config
print("martingale", config.martingale_enabled, "target", config.martingale_target,
      "base", config.base_stake_usd, "retry", config.retry_stake_usd,
      "ex", config.kalshi_exchange_index)
from app import martingale
cash = martingale.kalshi_cash()
print("live_cash", cash)
plan = martingale.plan_stake(cash)
print("PLAN", json.dumps(plan, indent=2))
print("--- ladder ---")
c = 0.71
for _ in range(6):
    p = martingale.plan_stake(c)
    print(f"streak={p['loss_streak']} cash={p['cash']:.2f} stake={p['stake']:.2f} mode={p['mode']} next={p.get('next_double')}")
    c = round(c - float(p["stake"]), 4)
    if c < 0.05:
        print("BUST")
        break
print("at_target_6", json.dumps(martingale.plan_stake(6.00)))
from app.spin import evaluate_spin
r = evaluate_spin(force_judge=True)
print("SPIN", json.dumps({k: r.get(k) for k in ("mode", "result", "side", "conf", "entry", "stake_usd", "reason")}))
print("MG", json.dumps(r.get("martingale")))
