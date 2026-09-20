import sys, os, json, time
root = r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot"
sys.path.insert(0, root)
os.chdir(root)
for m in list(sys.modules):
    if m.startswith("app."):
        del sys.modules[m]

from app.micro import fetch_microstructure
from app.sentiment import get_sentiment
from app.judge import judge
from app import martingale, kalshi_live
from app.spin import evaluate_spin, live_armed
import app.judge as jmod

print("=== JEV-X MICROSTRUCTURE ===")
micro = fetch_microstructure("BTC")
print(json.dumps({k: micro.get(k) for k in (
    "price", "change_24h_pct", "rsi_14", "funding_rate_pct",
    "open_interest_usd", "sources", "errors"
)}, indent=2))

print("=== X + SOCIAL + MICRO ===")
jmod._JUDGE_CACHE = {"ts": 0, "window_id": None, "judgment": None}
s = get_sentiment("BTC", force=True)
st = s["stats"]
print(json.dumps({
    "social_source": s.get("source"),
    "is_mock": s.get("is_mock"),
    "sample": st.get("sample_size"),
    "polarity": st.get("polarity_score"),
    "label": st.get("sentiment_label"),
    "micro_rsi": (s.get("micro") or {}).get("rsi_14"),
    "micro_fund": (s.get("micro") or {}).get("funding_rate_pct"),
}, indent=2))

print("=== FULL JUDGE (TypeSafe + Jev-X) ===")
j = judge(force=True)
print(json.dumps({
    "src": j.get("judge_src"),
    "side": j.get("side"),
    "conf": j.get("conf"),
    "action": j.get("trade_action"),
    "sentiment": j.get("sentiment_label"),
    "polarity": j.get("x_polarity") or j.get("polarity_score"),
    "squeeze": j.get("squeeze_risk_pct"),
    "rsi": (j.get("microstructure") or {}).get("rsi_14"),
    "funding": (j.get("microstructure") or {}).get("funding_rate_pct"),
    "reason": j.get("reason"),
    "yes_mid": j.get("yes_mid"),
    "ticker": (j.get("window") or {}).get("ticker"),
    "social_source": j.get("social_source"),
}, indent=2))

print("=== LIVE FILL ATTEMPT ===")
print("live_armed", live_armed())
kid, pk = kalshi_live.load_creds()
_st, mk = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/markets?limit=3&series_ticker=KXBTC15M&status=open")
m = (mk.get("markets") or [None])[0]
print("book", m.get("ticker"), "ex", m.get("exchange_index"),
      "yb", m.get("yes_bid_dollars"), "ya", m.get("yes_ask_dollars"),
      "na", m.get("no_ask_dollars"))
fund = kalshi_live.ensure_shard_funds(kid, pk, int(m.get("exchange_index") or 2), min_dollars=0.3)
print("fund", json.dumps(fund))
print("plan", json.dumps(martingale.plan_stake(fund.get("dest_cash"))))

# clear spun so this window can fire
open(os.path.join(root, "data", "spun_windows.json"), "w").write('{"done":[]}')
r = evaluate_spin(force_judge=True)
print("SPIN", json.dumps({k: r.get(k) for k in (
    "mode", "ticker", "result", "side", "conf", "entry", "stake_usd",
    "side_switch", "reason", "error", "filled"
)}, indent=2))
if r.get("order"):
    o = r["order"]
    print("ORDER", json.dumps({k: o.get(k) for k in (
        "filled", "count", "price", "est_cost", "book_side", "http_status", "error"
    )}, indent=2))
    print("RESP", json.dumps(o.get("response"))[:400])
print("cash_after", json.dumps(martingale.kalshi_cash()))
_st, bal = kalshi_live._kreq(kid, pk, "GET", "/trade-api/v2/portfolio/balance")
print("shards", json.dumps(bal.get("balance_breakdown")))
