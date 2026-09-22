#!/bin/bash
# Foreground desk start. wsl.exe must stay the parent; do not background this.
cd /home/jpanasuk/jev-15m-kalshi-bot || exit 1
mkdir -p data/logs
printf '%s\n' "[launcher] $(date -Iseconds) starting app.main" >> data/logs/desk.out
export JASPER_NO_PROMPT=1
exec .venv/bin/python -m app.main >> data/logs/desk.out 2>&1
