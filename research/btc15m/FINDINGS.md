# Findings

One pre-registered rule cleared a win rate above 57% on the design slice, again on the confirm slice, and again on the sealed last third of BTCUSDT 15-minute candles. That rule fades a run of six or more same-color candles. Eighteen rules cleared the design gate. Six of those cleared confirm. The sealed score kept one.

Shorter streak fades are the same bet with a looser trigger. They are not extra edges. Nothing here was wired into the live Kalshi order path.

## Contract and sample

Binance spot BTCUSDT, 15-minute bars, 319,198 closed candles from 2017-08-17 04:00 UTC through 2026-09-29 23:45 UTC. Checksums were checked on the Binance Vision files. The series has 32 gaps and 561 missing bars (0.175%). An up candle is close above open. A push is an equal close.

The payout is decimal 1.8, so a win profits 0.8 stake before fees. The fee is 0.06% of stake on every outcome. Breakeven is 55.59%. Half Kelly uses the design-slice win rate as the probability and never refits it. The 25% cap did not bind.

The sealed slice is the last 106,399 bars, 2023-09-17 16:15 UTC through 2026-09-29 23:45 UTC. It was scored once, and only for the six rules that had already passed design and confirm. The up-candle base rate was 50.66% on design, 50.16% on confirm, and 50.16% on the sealed slice. The kept rule fades a color streak. The base rate says the coin is close to a coin flip.

The grid was the same 152 rules used on ETH (150 eligible, plus always-up and always-down). It was not narrowed to the ETH survivors. The design median win rate was 50.04%. Hour-of-day and weekday maps locked nothing at the 57% / 800-trade bar. Momentum and trend sat below 50% (medians 47.66% and 48.79%). Channel, streak, and RSI sat higher (56.02%, 55.78%, and 55.57%). Forty-two rules with at least 500 trades beat 55%. Eighteen beat 57%. Three beat 60% on design, all of them streak fades, and the 63.70% length-7 rule died on confirm.

## What failed confirm

These twelve cleared 57% on 2017–2020 and did not repeat above 57% on 2020-09-03 through 2023-09-17. Half Kelly still bet the design win rate. A terminal above 1 is the compound of that locked fraction. It is not a pass.

| Rule | Design win rate | Confirm trades | Confirm win rate | Confirm half-Kelly terminal | Confirm max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| bb_fade_20_2p0 | 57.26% | 12,791 | 56.99% | 69.55 | 89.2% |
| stoch_fade_14_80_20 | 57.09% | 34,879 | 56.98% | 48,941 | 90.2% |
| stoch_fade_5_80_20 | 57.04% | 38,194 | 56.95% | 75,708 | 93.5% |
| rsi_fade_7_70_30 | 57.06% | 20,976 | 56.61% | 59.04 | 91.9% |
| rsi_fade_7_75_25 | 57.56% | 11,785 | 56.24% | 2.11 | 98.4% |
| body_fade_0p85 | 57.11% | 6,976 | 56.16% | 1.52 | 70.5% |
| vwap_fade_16_2p0 | 58.12% | 8,571 | 56.10% | 0.570 | 99.7% |
| streak_fade_7 | 63.70% | 743 | 55.99% | 0.132 | 98.6% |
| rsi_fade_7_80_20 | 57.97% | 6,113 | 55.60% | 0.178 | 99.4% |
| rsi_fade_14_75_25 | 57.44% | 3,842 | 52.84% | 0.010 | 99.6% |
| rsi_fade_21_75_25 | 59.10% | 1,645 | 51.79% | 0.004 | 99.9% |
| rsi_fade_14_80_20 | 59.24% | 1,428 | 51.75% | 0.006 | 99.8% |

`streak_fade_7` had the best design point estimate and 573 trades, just over the 500-trade floor. Confirm sized it at 9.13% of bankroll from that 63.70% design rate and the path lost most of the bankroll. The RSI 14 and 21 fades that looked strong on design fell to about 52%.

## What reached the sealed slice and missed 57%

| Rule | Sealed trades | Sealed win rate | Sealed Wilson 95% | Flat EV per 1 stake | Half-Kelly terminal | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| streak_fade_5 | 4,604 | 56.97% | 55.54% – 58.40% | +0.0249 | 1.22 | 96.6% |
| donchian_fade_10 | 16,437 | 56.93% | 56.17% – 57.68% | +0.0241 | 279.59 | 79.9% |
| streak_fade_4 | 10,527 | 56.22% | 55.27% – 57.16% | +0.0113 | 0.307 | 99.2% |
| streak_fade_3 | 23,500 | 55.17% | 54.54% – 55.81% | −0.0075 | ~0 | 100% |
| range_fade_8_0p8 | 41,975 | 54.96% | 54.48% – 55.44% | −0.0113 | ~0 | 100% |

`donchian_fade_10` had the best confirm win rate, 57.97% on 13,589 trades, and its sealed interval still clears breakeven. The sealed point estimate is 56.93%, under the keep bar. The 279x terminal is half Kelly at the design fraction, 2.30% of bankroll, compounded across 16,437 bets, with an 80% drawdown along the way. The rule was not kept.

`streak_fade_5` finished at 56.97%. On the ETH study the same rule stayed above 57% on the sealed third. On Bitcoin it did not.

## What stayed above 57%

After six or more consecutive candles of the same color, bet the next candle is the opposite color. Trades where the streak is already seven or longer are included. `streak_fade_7` itself failed confirm, so this sealed count was not split into "exactly six" and "seven or more."

| Slice | streak_fade_6 |
| --- | ---: |
| Design trades / win rate | 1,473 / 60.83% |
| Confirm trades / win rate | 1,747 / 57.47% |
| Sealed trades / win rate | 1,979 / 58.46% |
| Sealed Wilson 95% | 56.28% – 60.62% |
| Sealed flat EV per 1 stake | +0.0517 |
| Sealed flat PnL, 1 stake each trade | +102.41 |
| Half-Kelly fraction, locked from design | 5.899% |
| Sealed half-Kelly terminal, start at 1 | 27.19 |
| Sealed half-Kelly max drawdown | 82.8% |

On confirm the point estimate cleared 57% and the Wilson interval started at 55.14%, under breakeven. On the sealed slice the interval starts at 56.28%, so it clears breakeven at 95% and the lower bound itself is under 57%.

The sealed window is about 3.03 years of bars. The rule fired about 1.79 times a day, about 652 times a year. Flat-stake Sharpe, using the sealed win rate and this payout and ignoring pushes, is about 0.058 per trade and about 1.49 per year. A 57% win rate on every bar would look much larger. This rule does not trade every bar.

Subtracting the length-6 wins and losses from the length-5 sealed counts leaves the "streak is exactly five" bars at 1,466 / 2,625 = 55.85%. That subtraction is arithmetic on the published counts, not a separate sealed test. The same arithmetic on the confirm counts puts "exactly six" at 588 / 1,004 = 58.57%, with the seven-or-longer subset at the 55.99% confirm rate that already failed.

## What this is not

The live desk trades Kalshi Bitcoin `KXBTC15M`. Jev still names that side. This rule was not added to `app/spin.py`, `app/jev_layer.py`, or the order path. Kalshi's fee is not 0.06%, and a Binance candle close is not a filled Kalshi contract. There is no spread, no latency, and no missed fill in these numbers. Half Kelly on the kept rule still took an 83% drawdown on the sealed path. The terminal multiple is the compounded result of betting about 6% of a growing bankroll, not a flat stake.
