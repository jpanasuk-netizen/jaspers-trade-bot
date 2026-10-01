#!/bin/bash
# History site on :3002. wsl.exe must stay the parent; do not background this.
cd /home/jpanasuk/jev-15m-kalshi-bot || exit 1
mkdir -p data/logs
printf '%s\n' "[launcher] $(date -Iseconds) starting history_server" >> data/logs/history.out
export JASPER_NO_PROMPT=1
export HISTORY_HOST=0.0.0.0
export HISTORY_PORT=3002
# Keep Windows-visible IP file fresh so localhost_v6_proxy.py never needs wsl.exe (no console flash).
(
  echo jev_ubuntu_ip_writer_loop
  while true; do
    hostname -I | awk '{print $1}' > /mnt/c/Users/jpana/AppData/Local/Temp/jev_ubuntu_ip.txt 2>/dev/null || true
    hostname -I | awk '{print $1}' > /tmp/jev_ubuntu_ip.txt 2>/dev/null || true
    sleep 30
  done
) >/tmp/jev_ubuntu_ip_writer.log 2>&1 &
exec .venv/bin/python -m app.history_server >> data/logs/history.out 2>&1
