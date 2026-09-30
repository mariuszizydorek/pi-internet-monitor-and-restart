#!/bin/bash
# Save the Supabase secret key and create or update the remote tables.
#
#   ./scripts/setup-supabase.sh
#
# Press Enter to keep the project URL and secret key already on disk.
# The first run also asks for a personal access token from
# https://supabase.com/dashboard/account/tokens
# That token is what creates the tables. Sync reapplies supabase/*.sql
# on startup, so later schema files do not go through the SQL editor.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${NETWATCH_ROOT:-$HOME/.netwatch}"

if [ ! -f "$CONFIG/netwatch.env" ]; then
  echo "Missing $CONFIG/netwatch.env. Run ./scripts/setup-local.sh first." >&2
  exit 1
fi

current_url="$(grep '^SUPABASE_URL=' "$CONFIG/netwatch.env" | head -n 1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
read -r -p "Supabase project URL [${current_url}]: " SUPABASE_URL </dev/tty
SUPABASE_URL="${SUPABASE_URL:-$current_url}"
read -r -s -p "Supabase secret key sb_secret_... (Enter to keep the saved key): " SUPABASE_KEY </dev/tty
echo >/dev/tty
read -r -s -p "Supabase access token sbp_... (Enter to keep the saved token): " SUPABASE_ACCESS_TOKEN </dev/tty
echo >/dev/tty

PY="$REPO/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

export CONFIG SUPABASE_URL SUPABASE_KEY SUPABASE_ACCESS_TOKEN REPO
PYTHONPATH="$REPO" "$PY" - <<'PY'
import os
from pathlib import Path

import httpx

from netwatch.localapp.connectivity import check_supabase, key_problem
from netwatch.sync.schema import apply_sql_dir
from scripts.setup import save_supabase, write_secret

root = Path(os.environ["CONFIG"])
url = os.environ["SUPABASE_URL"].strip()
api_key = os.environ.get("SUPABASE_KEY", "").strip()
access_token = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
key_path = root / "secrets" / "supabase_key"
token_path = root / "secrets" / "supabase_access_token"

if api_key:
    url = save_supabase(root, url, api_key)
else:
    if not key_path.is_file():
        raise SystemExit("No secret key is saved yet.")
    api_key = key_path.read_text(encoding="utf-8").strip()
    problem = key_problem(api_key)
    if problem:
        raise SystemExit(problem)

if access_token:
    write_secret(root / "secrets", "supabase_access_token", access_token)
elif token_path.is_file():
    access_token = token_path.read_text(encoding="utf-8").strip()
else:
    raise SystemExit(
        "An access token is required once. Create one at "
        "https://supabase.com/dashboard/account/tokens and run this script again."
    )

with httpx.Client(timeout=60) as http:
    applied = apply_sql_dir(url, access_token, Path(os.environ["REPO"]) / "supabase", http)
    result = check_supabase(url, api_key, http)
print("Applied " + ", ".join(applied))
if not result["ok"]:
    raise SystemExit(result["detail"])
print(result["detail"])
PY
unset SUPABASE_KEY SUPABASE_ACCESS_TOKEN

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  export NETWATCH_CONFIG_DIR="$CONFIG"
  unset NETWATCH_DATA_DIR
  docker compose -f "$REPO/compose.yaml" --profile grafana up -d --force-recreate --no-deps sync grafana
  echo "Restarted sync and Grafana."
fi

echo "Check it at http://localhost:16081/admin"
