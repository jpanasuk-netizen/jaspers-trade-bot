"""Forward Windows localhost:3002 to the history server in Ubuntu.

The history process listens on 0.0.0.0:3002 inside the distro. Windows does
not publish that socket on 127.0.0.1, so a browser on this PC is refused.
This process owns 127.0.0.1:3002 and ::1:3002 and copies them to Ubuntu's
current IPv4 address.

::1:3000 still forwards to whatever is already bound on 127.0.0.1:3000.
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path

PORTS = (3000, 3002)
_ip_lock = threading.Lock()
_ip_cache = {"ip": "", "at": 0.0}

_IP_FILES = [
    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\jpana\AppData\Local")) / "Temp" / "jev_ubuntu_ip.txt",
    Path(r"C:\Users\jpana\AppData\Local\Temp\jev_ubuntu_ip.txt"),
    Path(r"\\wsl$\Ubuntu\tmp\jev_ubuntu_ip.txt"),
]


def _ubuntu_ipv4(force: bool = False) -> str:
    """Resolve Ubuntu eth0 IPv4 without flashing a Windows console.

    Prefer a file written inside WSL (no wsl.exe spawn from Windows). Fall back
    to a hidden wsl.exe call only if the file is missing/stale.
    """
    now = time.monotonic()
    with _ip_lock:
        cached = _ip_cache["ip"]
        if not force and cached and now - _ip_cache["at"] < 30:
            return cached

    ip = ""
    for path in _IP_FILES:
        try:
            if path.is_file():
                age = time.time() - path.stat().st_mtime
                if force or age < 120:
                    raw = path.read_text(encoding="utf-8", errors="ignore").strip().split()[0]
                    if raw and raw[0].isdigit():
                        ip = raw
                        break
        except OSError:
            continue

    if not ip:
        # Last resort: hidden wsl.exe (should rarely run once the WSL writer is up)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        out = subprocess.check_output(
            ["wsl.exe", "-d", "Ubuntu", "-e", "hostname", "-I"],
            text=True,
            timeout=8,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=si,
        )
        ip = out.split()[0]

    with _ip_lock:
        _ip_cache["ip"] = ip
        _ip_cache["at"] = time.monotonic()
    return ip


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def _dial(port: int) -> socket.socket:
    if port == 3002:
        try:
            return socket.create_connection((_ubuntu_ipv4(), port), timeout=8)
        except OSError:
            return socket.create_connection((_ubuntu_ipv4(force=True), port), timeout=8)
    return socket.create_connection(("127.0.0.1", port), timeout=8)


def _handle(client: socket.socket, port: int) -> None:
    try:
        remote = _dial(port)
    except OSError:
        client.close()
        return
    client.settimeout(None)
    left = threading.Thread(target=_pipe, args=(client, remote), daemon=True)
    right = threading.Thread(target=_pipe, args=(remote, client), daemon=True)
    left.start()
    right.start()
    left.join()
    right.join()


def _serve(bind: tuple[str, int], family: socket.AddressFamily) -> None:
    port = bind[1]
    server = socket.socket(family, socket.SOCK_STREAM)
    if family == socket.AF_INET6:
        server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(bind)
    except OSError as exc:
        print(f"[v6] {bind[0]}:{port} not bound ({exc})", flush=True)
        return
    server.listen(64)
    where = "ubuntu" if port == 3002 else "127.0.0.1"
    print(f"[v6] {bind[0]}:{port} -> {where}:{port}", flush=True)
    while True:
        client, _addr = server.accept()
        threading.Thread(target=_handle, args=(client, port), daemon=True).start()


def main() -> None:
    binds: list[tuple[tuple[str, int], socket.AddressFamily]] = [
        (("::1", 3000), socket.AF_INET6),
        (("::1", 3002), socket.AF_INET6),
        (("127.0.0.1", 3002), socket.AF_INET),
    ]
    threads = [
        threading.Thread(target=_serve, args=(bind, family), daemon=True)
        for bind, family in binds
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()