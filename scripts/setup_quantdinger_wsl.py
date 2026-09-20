#!/usr/bin/env python3
"""Configure QuantDinger env + pull GHCR stack inside WSL."""
from pathlib import Path
import os
import re
import secrets
import subprocess
import sys

root = Path("/opt/quantdinger")
if not (root / "docker-compose.ghcr.yml").exists():
    print("missing /opt/quantdinger", file=sys.stderr)
    sys.exit(1)

def setk(text: str, key: str, value: str) -> str:
    if re.search(rf"^#?{re.escape(key)}=", text, flags=re.M):
        return re.sub(rf"^#?{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
    return text + f"\n{key}={value}\n"

sk = secrets.token_hex(32)
ck = secrets.token_hex(32)
pg = secrets.token_hex(16)
rd = secrets.token_hex(16)
cr = secrets.token_hex(16)
gf = secrets.token_hex(16)
admin_pw = secrets.token_urlsafe(12) + "Aa1!"
typesafe = (os.environ.get("TYPESAFE_API_KEY") or "").strip()
if not typesafe:
    print("TYPESAFE_API_KEY not set — skipping JEV keys in backend.env", file=sys.stderr)

env_path = root / ".env"
if not env_path.exists():
    example = root / ".env.example"
    env_path.write_text(example.read_text() if example.exists() else "")
t = env_path.read_text()
for k, v in {
    "POSTGRES_PASSWORD": pg,
    "REDIS_PASSWORD": rd,
    "CELERY_REDIS_PASSWORD": cr,
    "GRAFANA_ADMIN_PASSWORD": gf,
    "BACKEND_PORT": "0.0.0.0:5000",
    "FRONTEND_HOST": "0.0.0.0",
    "FRONTEND_PORT": "8888",
    "MOBILE_HOST": "0.0.0.0",
    "MOBILE_PORT": "8889",
}.items():
    t = setk(t, k, v)
env_path.write_text(t)

be = root / "backend_api_python" / ".env"
src = root / "backend_api_python" / "env.example"
if not be.exists():
    be.write_text(src.read_text() if src.exists() else "")
bt = be.read_text()
for k, v in {
    "SECRET_KEY": sk,
    "CREDENTIAL_ENCRYPTION_KEY": ck,
    "ADMIN_USER": os.environ.get("QD_ADMIN_USER", "admin"),
    "ADMIN_PASSWORD": admin_pw,
    "REDIS_PASSWORD": rd,
    "CELERY_REDIS_PASSWORD": cr,
    "JEV_BASE_URL": "https://api.typesafe.ai/v1",
    "JEV_MODEL": "jev-1.13.0",
    "JEV_TIMEOUT_SECONDS": "2",
}.items():
    bt = setk(bt, k, v)
if typesafe:
    bt = setk(bt, "JEV_API_KEY", typesafe)
be.write_text(bt)

(root / "DESK_ADMIN.txt").write_text(
    f"ADMIN_USER={os.environ.get('QD_ADMIN_USER', 'admin')}\nADMIN_PASSWORD={admin_pw}\nWEB=http://127.0.0.1:8888\nAPI=http://127.0.0.1:5000/api/health\n"
)
print("wrote env")
print("ADMIN_USER=" + os.environ.get("QD_ADMIN_USER", "admin"))
print("ADMIN_PASSWORD=" + admin_pw)
print("--- compose up ---")
r = subprocess.run(
    ["docker", "compose", "-f", "docker-compose.ghcr.yml", "up", "-d", "--pull", "always"],
    cwd=str(root),
)
sys.exit(r.returncode)
