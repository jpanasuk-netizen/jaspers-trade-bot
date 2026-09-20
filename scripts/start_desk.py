import subprocess
import sys
import time
import urllib.request

cmd = [
    r"C:\Users\jpana\AppData\Local\Programs\Xiaomi MiMo AI\resources\runtimes\win32-x64\python\python.exe",
    "-m",
    "app.main",
]
# detached process via CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
log = open(r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot\data\logs\desk.out", "a", encoding="utf-8")
proc = subprocess.Popen(
    cmd,
    cwd=r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot",
    stdout=log,
    stderr=subprocess.STDOUT,
    creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
    close_fds=True,
)
print(f"started pid={proc.pid}")
time.sleep(8)
try:
    with urllib.request.urlopen("http://127.0.0.1:3000/api/health", timeout=5) as r:
        print("health", r.status, r.read()[:200])
except Exception as e:
    print("health fail", e)
try:
    with urllib.request.urlopen("http://127.0.0.1:3000/api/state", timeout=8) as r:
        import json
        d = json.loads(r.read())
        ch = d.get("charts") or {}
        print("charts spot", len(ch.get("spot") or []), "book", len(ch.get("book") or []), "models", len(ch.get("models") or []))
        print("conn", d.get("connection"), "price", (d.get("market_fresh") or {}).get("price"))
        last = d.get("last_judgment") or {}
        print("judge", last.get("side"), last.get("judge_src"), last.get("route"))
except Exception as e:
    print("state fail", e)
