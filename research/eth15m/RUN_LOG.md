# ETH 15m research run log

## Split locked

- source: binance-vision-spot
- bars: 319198
- first: 2017-08-17T04:00:00Z
- last: 2026-09-29T23:45:00Z
- design rows: 106399 (2017-08-17T04:00:00Z to 2020-09-03T08:45:00Z)
- confirm rows: 106400 (2020-09-03T09:00:00Z to 2023-09-17T16:00:00Z)
- sealed rows: 106399 (2023-09-17T16:15:00Z to 2026-09-29T23:45:00Z)
- gaps: {'gap_events': 32, 'missing_bars': 561, 'max_gap_ms': 121394800}
- file sha256: b5f17c442559b7f23444045869119775d8ccd50cd2e16549e2d30d02fd6bab29
- sealed sha256: 02b7695550f1160754102f75e65f136584a85595681651c060fe385da74c6d1a
- source hash: 7b42bb55dc2f879c25a0ddb16d009f2b1f6dbefb662ef11aa6645a94f34f815a
- strategies: 152

## Design

- base up rate: 0.501051169604551
- eligible: 150
- with minimum trades: 146
- passed: 5
- median win rate: 0.4991233920914721
- max win rate: 0.5911214953271028
- hour locks: []
- weekday locks: []

## Confirm

- design passers scored: 5
- confirm base up rate: 0.5032283568322572
- passed: 2
- median win rate: 0.5530295019562229
- max win rate: 0.5901001112347052

## Sealed

- confirm passers scored: 2
- sealed base up rate: 0.504600015051174
- kept: ['streak_fade_5', 'streak_fade_6']
- passed: 2
- max win rate: 0.5935946990612921
