"""Forward Chrome's IPv6 localhost to the desk.

WSL answers 127.0.0.1:3000 and :3002. Chrome often opens "localhost" as ::1,
and nothing is listening there, so the browser says the connection was refused.
This process listens only on ::1 and copies those connections to 127.0.0.1.
"""
from __future__ import annotations

import socket
import threading

PORTS = (3000, 3002)


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


def _handle(client: socket.socket, port: int) -> None:
    try:
        remote = socket.create_connection(("127.0.0.1", port), timeout=8)
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


def _serve(port: int) -> None:
    server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("::1", port))
    except OSError as exc:
        print(f"[v6] ::1:{port} not bound ({exc})", flush=True)
        return
    server.listen(64)
    print(f"[v6] ::1:{port} -> 127.0.0.1:{port}", flush=True)
    while True:
        client, _addr = server.accept()
        threading.Thread(target=_handle, args=(client, port), daemon=True).start()


def main() -> None:
    threads = [threading.Thread(target=_serve, args=(port,), daemon=True) for port in PORTS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
