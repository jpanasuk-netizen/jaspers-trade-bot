#!/bin/bash
# Run one Bitcoin research stage after the harness allows it. Does not trade.
set -euo pipefail
HARNESS="/home/jpanasuk/jev-15m-kalshi-bot/research/btc15m/harness_check.py"
if [ "$#" -lt 1 ]; then
  echo "usage: run_stage.sh /absolute/path/to/script.py [args...]" >&2
  exit 2
fi
export PYTHONUNBUFFERED=1
CMD="/usr/bin/python3"
for arg in "$@"; do
  CMD+=" $(printf '%q' "$arg")"
done
GATE="$(/usr/bin/python3 "$HARNESS" "$CMD")"
printf '%s\n' "$GATE"
DECISION="$(/usr/bin/python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["decision"]["decision"])' <<<"$GATE")"
if [ "$DECISION" != "allow" ]; then
  echo "harness $DECISION; not running $CMD" >&2
  exit 2
fi
exec /usr/bin/python3 "$@"
