# Patch notes — 2026-09-21

Saved on top of `eaf69ab` (Share desk: Jev battery, late-window fire, strip setup secrets).

The live Kalshi BTC 15-minute desk. Jev names the side. Code places the order. The ticket is held to settlement.

## How a buy works now

- The side is Jev's YES or NO. The desk does not flip to the cheaper opposite contract.
- That side is bought when the ask is **76¢ or less** (`ENTRY_CEIL=0.76`). Above that, the window is skipped.
- The extra gates that were blocking fills are off: the spot-vs-open tape veto, the 20¢ floor, and the outside panel (book, QuantDinger, fib/Hurst, AI-Trader crowd, sentiment).
- If Jev's own battery says `SKIP` (confidence, signal quality, consistency, or toxic flow), the order does not go out. A leaned YES/NO is not traded through that skip.
- A Jev answer that takes one or two seconds is on time. The wait is 2.5 seconds. Only a miss past that is a hold.
- One try per window. A fill, a miss, or an error marks the window done so it is not sent again every few seconds.
- A miss stays a miss. The desk no longer leaves a resting order that can fill later.
- A normal spin spends about **$2**, which can be more than one contract. Recovery under the $6 target is still capped at one contract.
- The desk looks about every 1.5 seconds for the whole window.
- The volatility ceiling is 2.8. The old 2.2 sat under a normal Bitcoin reading and froze the desk.
- Open tickets are held. An early sale that dumped two YES winners was removed.

## Jev

- One call to `https://api.typesafe.ai/v1/systemone`, model pinned at `jev-1.13.0`.
- The battery is side, regime, toxic flow, signal quality, agreement, and whether to escalate.
- Code still owns the 76¢ cap, the stake, and the order.

## Charts

- On `http://127.0.0.1:3000`, the Bitcoin chart has an **OVER/UNDER** line at the window open.
- The fair-value chart has the same line at 0.50.
- The line is drawn on top of the price so it stays visible when Bitcoin is sitting on the open.

## Logs and scoreboard

- A window that ends with no trade writes **one** skip line, not a line every poll.
- The scoreboard counts wins, losses, and profit from Kalshi settlement.
- History on port 3002 can be cleared without deleting the "already traded this window" lock.

## Added, but not allowed to place orders

- **Argus gates** (`app/argus_gate.py`). Sharpe, drawdown, hit rate, and t-stat must pass on data the rule was not fit on, and again on a sealed slice, before the stake is allowed to grow past $2. Failing the gates does not stop the $2 spin.
- **AI-Trader** (`app/ai_trader.py`). Read-only Bitcoin crowd from the public feed. It does not copy anyone's orders.
- **FinanceDatabase** (`app/finance_db.py`). The catalog's Bitcoin pairs (`BTC2-USD` and the other currencies) are listed for the HUD and for Jev's snapshot. It is not a price feed.

## Also in this save

- Settings page and settlement helper that were sitting untracked.
- `websockets` so the fast price feed can use a socket instead of only REST.

## Desktop exe

`Kalshi 15m Desk.exe` asks for any missing key before it starts the desk:

- TypeSafe Jev API key
- Kalshi API key id
- Full path to the Kalshi private key file

Press Enter to keep a key that is already saved. A headless start does not ask.

## Not in the commit

- `.env` stays on the machine. The knobs that matter are `ENTRY_CEIL=0.76`, `MAX_VOL_PROXY=2.8`, and `JEV_TIMEOUT_SEC=2.5`.
- No API keys, no Kalshi secrets.
