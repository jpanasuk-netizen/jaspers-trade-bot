#!/bin/bash
# History site on :3002. wsl.exe must stay the parent; do not background this.
cd /home/jpanasuk/jev-15m-kalshi-bot || exit 1
mkdir -p data/logs
printf '%s\n' "[launcher] $(date -Iseconds) starting history_server" >> data/logs/history.out
export JASPER_NO_PROMPT=1
export HISTORY_HOST=0.0.0.0
export HISTORY_PORT=3002
exec .venv/bin/python -m app.history_server >> data/logs/history.out 2>&1
