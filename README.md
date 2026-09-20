# Jasper's Trade Bot

15-min BTC JAP · Kalshi YES/NO desk. Live HUD, decision history, JEV + BTCC + QuantDinger.

Regime-adaptive trading desk for **Kalshi KXBTC15M** (Bitcoin 15-minute YES/NO).

Architecture follows **JEV / TypeSafe System One** + **QuantDinger-BTC** + **Grokbot BTCC** doctrine:

```
Layer 1     deterministic stats (HMM regime, BOCPD, OFI, VPIN, fib/golden pocket, Hurst)
Layer 1.5   JEV typed battery (Choice / Noul / Score) — triage only
QuantDinger fair-vs-book BTC models (local fallback when API down)
BTCC        signal board + hygiene (hygiene currently override OFF — recover mode)
Risk gate   hard vetoes — any fail = no trade
Execute     paper / live Kalshi orders in code — never the model
```

## Features

- **Fast-ahead feed** — races Kalshi hosts + BTC spot (Coinbase/Kraken/Bitstamp); ~40–70ms book
- **Live HUD** — scrolling desk with charts, trade-gate R/Y/G indicators, BTCC board, quant lab
- **History** — `/history` looks back on every spin / skip / live fill from the local ledger
- **JEV pipeline** — pinned `jev-1.13.0`, batched typed questions
- **Quant lab** — Brier / hit-rate / Sharpe from live fair-vs-open calibration ticks
- **Recover mode** — target $6, martingale, hygiene nix, no auto 500x

## Quick start

```powershell
cd jev-15m-kalshi-bot
# optional: copy .env.example → .env and fill keys
python -m pip install typesafe-sdk cryptography websockets requests
python -m app.main
# history site (separate process)
python -m app.history_server
# open http://127.0.0.1:3002/
# HUD: http://127.0.0.1:3000/
```

Windows one-shot:

```powershell
.\start_desk.cmd
```

## Config (`.env` — not in git)

| Key | Meaning |
|---|---|
| `TYPESAFE_API_KEY` | JEV / TypeSafe |
| `TYPESAFE_MODEL` | pin e.g. `jev-1.13.0` |
| `QUANTDINGER_BASE_URL` | e.g. `http://127.0.0.1:5000` |
| `QUANTDINGER_SYMBOL` | `BTC/USDT` |
| `BTCC_HYGIENE_ENFORCE` | `0` = hygiene OFF (recover) |
| `RECOVER_TARGET_USD` | bankroll target (default 6) |
| `KALSHI_*` | live trading creds (local only) |
| `LIVE_MARK_PATH` | file that arms live orders |

## API

| Path | Purpose |
|---|---|
| `/` | Live HUD (`:3000`) |
| history site | `http://127.0.0.1:3002/` — full ledger, result mix, martingale climb |
| `/history` | Decision history (ledger replay) |
| `/api/state` | Full desk state (charts, gates, BTCC, quant) |
| `/api/btcc` | BTCC signal board |
| `/api/quant` | Quant lab snapshot |
| `/api/quantdinger` | QD + BTC pack |
| `/api/charts` | Rolling series |
| `/api/judgment` | Force judge |
| `/api/spin` | Force spin (paper/live) |
| `/api/history` | Ledger rows + fill/skip stats |

## Safety

- **Hard risk gate** — exposure, freshness, day-stop, confidence floors
- **No auto 500x** — Kalshi stake cap only; leverage bots are out of scope
- **LIVE** only when `LIVE_MARK` is armed **and** Kalshi keys exist
- Secrets never committed — see `.gitignore`

## License

Private / operator-owned. Not affiliated with Anthropic, Kalshi, or Open Byte.
JEV/TypeSafe is used as a judgment layer only; execution stays in code.
