# Findings

Two pre-registered rules cleared a win rate above 57% on the design slice, again on the confirm slice, and again on the sealed last third of ETHUSDT 15-minute candles. Both fade a run of same-color candles. They are one effect, not two independent edges. Nothing here was wired into the live Kalshi order path.

## Contract and sample

Binance spot ETHUSDT, 15-minute bars, 319,198 closed candles from 2017-08-17 04:00 UTC through 2026-09-29 23:45 UTC. Checksums were verified on the Binance Vision files. The series has 32 gaps and 561 missing bars (0.175%). An up candle is close above open. A push is an equal close.

The payout is decimal 1.8, so a win profits 0.8 stake before fees. The fee is 0.06% of stake on every outcome. Breakeven is 55.59%. Half Kelly uses the design-slice win rate as the probability and never refits it. The 25% cap did not bind.

The sealed slice is the last 106,399 bars, 2023-09-17 16:15 UTC through 2026-09-29 23:45 UTC. It was scored once, and only for rules that had already passed design and confirm. The up-candle base rate was 50.11% on design, 50.32% on confirm, and 50.46% on the sealed slice. The edge is not "ETH goes up."

The grid was 152 rules (150 eligible, plus always-up and always-down). The design median win rate was 49.91%. Hour-of-day and weekday maps locked nothing at the 57% / 800-trade bar. Trend-following families sat below 50%. Fade families sat above it. Five rules passed design. Three of those five failed confirm.

## What failed confirm

These three cleared 57% on 2017–2020 and did not repeat on 2020-09-03 through 2023-09-17. Half Kelly still bet the design win rate, so the paths lost money.

| Rule | Design win rate | Confirm trades | Confirm win rate | Confirm half-Kelly terminal | Confirm max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| rsi_fade_14_80_20 | 59.11% | 1,320 | 53.86% | 0.085 | 98.3% |
| rsi_fade_21_75_25 | 57.33% | 1,514 | 55.02% | 0.585 | 73.4% |
| vwap_fade_16_2p0 | 57.40% | 9,457 | 55.30% | 0.076 | 99.8% |

`rsi_fade_21_75_25` was already weak on design: its 95% Wilson interval started at 54.85%, under breakeven. The point estimate was what let it through.

## What stayed above 57%

After five or more consecutive candles of the same color, bet the next candle is the opposite color. After six, the same bet, on a smaller set. The length-6 trades are a subset of the length-5 trades.

| Slice | streak_fade_5 | streak_fade_6 |
| --- | ---: | ---: |
| Design trades / win rate | 4,260 / 58.85% | 1,731 / 58.41% |
| Confirm trades / win rate | 4,286 / 57.93% | 1,798 / 59.01% |
| Sealed trades / win rate | 4,325 / 58.10% | 1,811 / 59.36% |
| Sealed Wilson 95% | 56.63% – 59.57% | 57.08% – 61.60% |
| Sealed flat EV per 1 stake | +0.0453 | +0.0679 |
| Sealed flat PnL, 1 stake each trade | +195.80 | +122.91 |
| Half-Kelly fraction, locked from design | 3.671% | 3.171% |
| Sealed half-Kelly terminal, start at 1 | 130.77 | 24.03 |
| Sealed half-Kelly max drawdown | 84.9% | 41.7% |

On the sealed window that is about 3.03 years of bars, length 5 fired about 3.9 times a day and length 6 about 1.6 times a day. Flat-stake Sharpe, using only the sealed win rate and the payout, is about 1.92 per year for length 5 and about 1.88 for length 6. The self-test figure of about 5.3 is what 57% would mean if a rule traded every bar. These rules do not.

Length 6 is the stricter cut. Its sealed interval starts above 57%. Length 5's interval starts at 56.63%, so it clears 57% as a point estimate and clears breakeven at 95%, and the lower bound itself is not above 57%. Subtracting the length-6 wins and losses from the length-5 counts leaves the "streak is exactly five" bars at 1,438 / 2,514 = 57.20%. That subtraction is arithmetic on the published counts, not a separate sealed test.

## What this is not

The live desk trades Kalshi Bitcoin `KXBTC15M`. Jev still names that side. These ETH rules were not added to `app/spin.py`, `app/jev_layer.py`, or the order path. Kalshi's fee is not 0.06%, and a Binance candle close is not a filled Kalshi contract. Half Kelly on the length-5 rule still took an 85% drawdown on the sealed path. The terminal multiple is the compounded result of betting a few percent of a growing bankroll, not a flat stake.
