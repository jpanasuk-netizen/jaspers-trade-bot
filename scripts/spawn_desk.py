import subprocess, sys, os
root = r"C:\Users\jpana\XiaomiMiMoProjects\.mimo-sessions\2026-09-19\https---github.com-brainstormity-Jev-X-S\jev-15m-kalshi-bot"
py = r"C:\Users\jpana\AppData\Local\Programs\Python\Python313\python.exe"
out = open(os.path.join(root, "data", "desk.out"), "w", encoding="utf-8")
err = open(os.path.join(root, "data", "desk.err"), "w", encoding="utf-8")
subprocess.Popen(
    [py, "run_desk.py"],
    cwd=root,
    stdout=out,
    stderr=err,
    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
)
print("spawned")
