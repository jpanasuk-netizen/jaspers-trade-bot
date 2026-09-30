# ETH 15-minute up/down study

Pre-registered before any candle is scored. The code hash in `manifest.json` is the lock. Later stages refuse to run if that hash changes.

This is a research log for the Kalshi 15-minute desk repository. It does not pick YES or NO, and it does not change the live order path. The desk trades Bitcoin `KXBTC15M`. These rules are about Ethereum candles.

## Contract

- Venue candles: Binance spot `ETHUSDT`, 15-minute bars. An up candle is `close > open`. A down candle is `close < open`. An equal close is a push.
- Decision time is the open of the candle being predicted. The signal may use only bars that have already closed.
- Decimal payout is 1.8. A winning stake returns 1.8 times the stake, including the stake, so the profit before fees is 0.8.
- Fee is 0.06% of the stake, charged on a win, a loss, and a push.
- Breakeven win rate is `(1 + 0.0006) / 1.8` = 55.5888...%.
- A rule is kept only when its win rate is strictly above 57% and it has at least 500 decided trades. Pushes are not wins or losses.
- That 57% bar is about 1.4 percentage points above breakeven. On a rule that trades every bar, a true 57% hit rate would be a Sharpe near 5 per year before sizing. The bar is intentionally hard. A null result is an acceptable outcome.
- Half Kelly uses the design-slice win rate as `p`, including on later slices. The fraction is `0.5 * (b*p - q) / b` with `b = 0.7994 / 1.0006`. It is capped at 25% of bankroll. The cap is a numerical rail. If it binds, the result is suspect.
- Sizing on the design slice is in-sample. Confirm and sealed equity curves use the locked design `p` and are not refit.
- Controls `always_up` and `always_down` are reported and cannot be kept.

## Split

Bars are ordered by open time. The sealed slice is the last `floor(n/3)` bars. The visible prefix is split in half: design, then confirm.

Calendar rules are the exception inside the design slice. The hour-of-day and weekday maps are fit on the first half of design, and the design gate for those two rules uses only the second half of design. Confirm and sealed use that same locked map. They do not refit.

The sealed file is scored once, and only for rules that passed both design and confirm. The sealed script also records the sealed up-candle base rate. It does not search the sealed bars for a new rule.

## Grid

Every fully specified rule below is its own test. Parameters are not picked after seeing a score. The names written into the manifest at fetch time are the whole grid.

- Candle color: follow, fade.
- Close-to-close momentum and reversal, lookbacks 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96.
- Candle-color streaks: fade lengths 2 through 8, follow lengths 2 through 6.
- RSI fade at periods 7, 14, 21 and bands 60/40, 65/35, 70/30, 75/25, 80/20. RSI follow is the side of 50 for the same periods.
- EMA cross pairs (3, 8), (5, 13), (8, 21), (12, 26), (20, 50), (21, 55). EMA side periods 8, 20, 50, 100, 200.
- Bollinger fade and break, population standard deviation, pairs (20, 1.5), (20, 2), (20, 2.5), (48, 2).
- Return z-score fade and follow, lookbacks 20, 48, 96, thresholds 1, 1.5, 2, 2.5. The window excludes the bar being scored.
- Volume spike follow and fade, 20-bar baseline excluding the spike bar, multipliers 1.5, 2, 3.
- Donchian break and fade, windows 10, 20, 48, 96. The prior channel excludes the bar that just closed.
- MACD histogram sign, 12, 26, 9.
- Stochastic fade and follow, raw %K, (14, 80/20), (14, 70/30), (5, 80/20).
- Range-position break and fade, windows 8, 16, 32, 96, threshold 0.8.
- Body-to-range follow at 0.5 and 0.7. Body-to-range fade at 0.7 and 0.85.
- VWAP distance in ATR units, lookbacks 16, 48, 96, multiples 1 and 2, fade and follow.
- ATR-regime color momentum, ATR 14, rank 96, trade only in the top 30% or bottom 30% of recent ATR.
- Hour-of-day lock and weekday lock. A bucket locks only with at least 800 decided candles and a side above 57% inside the fit window.
- Controls: always up, always down.

Not in the grid, and not to be added after scores exist: machine-learning fits, searched rule combinations, a second pass that keeps the best lookback and retests it, and anything fit on confirm or sealed bars.

## Why these families

Short-horizon crypto research has two durable, small effects: reversal at the shortest horizons, and continuation after a move that has already shown some persistence. Range, band, RSI, and stochastic rules are the usual ways of writing those two bets. Volume and ATR rules ask whether the bet should be restricted to active or quiet markets. Hour and weekday rules ask whether the drift is a session effect rather than a price pattern. None of these families has a published 15-minute hit rate near 57% after costs. They are here so the log shows that the standard rules were actually run, not so that one of them can be tuned until it clears the bar.

## Stages

1. `selftest.py` on synthetic bars: payout identity, no lookahead under truncation, calendar keys, the 57% rule.
2. `fetch_split.py` writes the cache, the manifest, and the hashes. It does not score.
3. `run_design.py` scores the grid on the design slice.
4. `run_confirm.py` scores only design survivors.
5. `run_sealed.py` scores only confirm survivors, once.

`data/` on this desk is gitignored, and so are `*.jsonl` files. The cache of raw candles stays gitignored. The manifest, protocol, run log, and stage JSON files are the record that gets pushed.
