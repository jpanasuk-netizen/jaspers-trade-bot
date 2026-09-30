# BTC 15m research run log

## Split locked

- symbol: BTCUSDT
- source: binance-vision-spot
- bars: 319198
- first: 2017-08-17T04:00:00Z
- last: 2026-09-29T23:45:00Z
- design rows: 106399 (2017-08-17T04:00:00Z to 2020-09-03T08:45:00Z)
- confirm rows: 106400 (2020-09-03T09:00:00Z to 2023-09-17T16:00:00Z)
- sealed rows: 106399 (2023-09-17T16:15:00Z to 2026-09-29T23:45:00Z)
- gaps: {'gap_events': 32, 'missing_bars': 561, 'max_gap_ms': 121394789}
- file sha256: d703e99b50efc4acf94a293b66ffad6371304c354ce2671259ac93ae359530fe
- sealed sha256: d0c6499590d2450bb6ff7c11e559bdd949b620946023a4fc415b471297430e81
- source hash: 7b42bb55dc2f879c25a0ddb16d009f2b1f6dbefb662ef11aa6645a94f34f815a
- driver hash: 35ac07adc075987edfd7a8fb840008429eddc5ac5d2c3899b34468d43c7d7094
- strategies: 152

## Design

- base up rate: 0.506628698587512
- eligible: 150
- with minimum trades: 146
- passed: 18
- median win rate: 0.5004388738402876
- max win rate: 0.6369982547993019
- hour locks: []
- weekday locks: []

## Confirm

- design passers scored: 18
- confirm base up rate: 0.5015701982022641
- passed: 6
- median win rate: 0.5660755148741419
- max win rate: 0.579733608065347

## Sealed

- confirm passers scored: 6
- sealed base up rate: 0.5015702867889046
- kept: ['streak_fade_6']
- passed: 1
- max win rate: 0.5846387064173825
