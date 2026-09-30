#!/bin/bash
# Run one research stage after the harness allows it. Does not trade.
set -euo pipefail
ROOT="/home/jpanasuk/jev-15m-kalshi-bot/research/eth15m"
TARGET="${1:?stage script required}"
export PYTHONUNBUFFERED=1
GATE="$(/usr/bin/python3 "$ROOT/harness_check.py" "/usr/bin/python3 $TARGET")"
printf '%s\n' "$GATE"
DECISION="$(/usr/bin/python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["decision"]["decision"])' <<<"$GATE")"
if [ "$DECISION" != "allow" ]; then
  echo "harness $DECISION; not running $TARGET" >&2
  exit 2
fi
exec /usr/bin/python3 "$TARGET"
