# BTC 15-minute up/down study

Same contract and the same pre-registered grid as `research/eth15m`. The symbol is Binance spot `BTCUSDT`. The grid is not narrowed to the rules that survived on ETH. Each rule has to clear Bitcoin on its own.

## Contract

- Up means close above open. Down means close below open. An equal close is a push.
- Decimal payout is 1.8. Fee is 0.06% of stake on a win, a loss, and a push.
- Breakeven win rate is `(1 + 0.0006) / 1.8` = 55.59%.
- Keep a rule only when the win rate is strictly above 57% and there are at least 500 decided trades.
- Half Kelly uses the design-slice win rate as `p` on every later slice. The fraction is capped at 25% of bankroll.
- Controls `always_up` and `always_down` are reported and cannot be kept.

## Split

Bars are ordered by open time. The sealed slice is the last `floor(n/3)` bars. The visible prefix is split in half: design, then confirm.

Hour-of-day and weekday maps are fit on the first half of design. Their design gate uses only the second half. Confirm and sealed use that locked map and do not refit.

The sealed slice is scored once, and only for rules that passed design and confirm. The sealed script also records the sealed up-candle base rate. It does not search the sealed bars for a new rule.

## Grid

The names are the ones built by `research/eth15m/strategies.py`. The manifest records that list and the hash of the shared research code before any Bitcoin score. The stages refuse to run if that hash changes.

The split lock also stores a hash of this file, `sit.py`, `fetch_split.py`, `stage.py`, `run_stage.sh`, and `harness_check.py`. Design, confirm, and sealed refuse if that driver hash changes. Findings are written after the sealed score and are not part of the hash.

This study does not pick a Kalshi YES or NO and does not change the live order path.
