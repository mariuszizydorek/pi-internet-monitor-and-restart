#!/bin/bash
# Set up and optionally start the monitor on this laptop.
# Config and secrets go in ~/.netwatch, not /etc/netwatch.
#
#   ./scripts/setup-local.sh
#   ./scripts/setup-local.sh --start
#   ./scripts/setup-local.sh --stop
#   ./scripts/setup-local.sh --reconfigure

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${NETWATCH_ROOT:-$HOME/.netwatch}"
VENV="$REPO/.venv"
START=0
STOP=0
RECONFIGURE=0

for arg in "$@"; do
  case "$arg" in
    --start) START=1 ;;
    --stop) STOP=1 ;;
    --reconfigure) RECONFIGURE=1 ;;
    -h|--help)
      echo "Usage: ./scripts/setup-local.sh [--start] [--stop] [--reconfigure]"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

stop_services() {
  mkdir -p "$CONFIG/run"
  for name in monitor speedtest sync restart status; do
    pidfile="$CONFIG/run/${name}.pid"
    if [ -f "$pidfile" ]; then
      pid="$(cat "$pidfile")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "Stopped $name ($pid)"
      fi
      rm -f "$pidfile"
    fi
  done
  if command -v docker >/dev/null 2>&1; then
    docker rm -f netwatch-grafana >/dev/null 2>&1 || true
    export NETWATCH_CONFIG_DIR="$CONFIG"
    docker compose -f "$REPO/compose.yaml" --profile grafana stop >/dev/null 2>&1 || true
  fi
}

start_host() {
  local label="$1"
  local bin="$2"
  mkdir -p "$CONFIG/logs" "$CONFIG/run"
  # shellcheck disable=SC1090
  source "$CONFIG/env.sh"
  nohup "$VENV/bin/$bin" >>"$CONFIG/logs/${label}.log" 2>&1 &
  echo $! >"$CONFIG/run/${label}.pid"
  echo "Started $label on this machine ($!)"
}

compose_up() {
  export NETWATCH_CONFIG_DIR="$CONFIG"
  unset NETWATCH_DATA_DIR SQLITE_JOURNAL
  local services=(monitor speedtest sync status grafana)
  if [ -e /dev/gpiochip0 ]; then
    services+=(restart)
  else
    echo "Restart was not started: this machine has no /dev/gpiochip0."
  fi
  docker compose -f "$REPO/compose.yaml" --profile grafana up -d --build --pull "${services[@]}"
  echo "SQLite is on the netwatch-data volume, mounted at /data in each service."
  echo "Live status: http://localhost:16081"
  echo "Admin:       http://localhost:16081/admin"
  echo "Grafana:     http://localhost:16080"
}

ask() {
  local __var="$1"
  local label="$2"
  local default="${3:-}"
  local value
  if [ -n "$default" ]; then
    read -r -p "$label [$default]: " value </dev/tty
    value="${value:-$default}"
  else
    read -r -p "$label: " value </dev/tty
  fi
  printf -v "$__var" '%s' "$value"
}

ask_secret() {
  local __var="$1"
  local label="$2"
  local value
  read -r -s -p "$label: " value </dev/tty
  echo >/dev/tty
  printf -v "$__var" '%s' "$value"
}

require_value() {
  if [ -z "$2" ]; then
    echo "$1 is required" >&2
    exit 1
  fi
}

collect_settings() {
  echo "Enter the settings for this laptop. Press Enter to accept a value in brackets."
  echo "Run supabase/001_init.sql in the Supabase SQL editor before the first sync."
  echo
  ask CONFIG "Folder for config, secrets, and the local database" "$CONFIG"
  ask SITE_ID "SITE_ID (name stored on every row, so this laptop is distinct from a Pi)"
  ask INTERFACES "Interfaces to watch, comma-separated" "en0"
  ask DECO_HOST "Deco LAN address" "192.168.68.1"
  ask DECO_USER "Deco admin username" "admin"
  ask_secret DECO_PASSWORD "Deco admin password"
  ask SUPABASE_URL "Supabase project URL (https://YOUR-PROJECT.supabase.co)"
  ask_secret SUPABASE_KEY "Supabase secret key (sb_secret_... from Project Settings, API Keys)"
  ask GPIO_ENABLED "Enable GPIO router restart on this machine? (yes/no)" "no"
  GPIO_CHIP="gpiochip0"
  GPIO_LINE=""
  case "$(printf '%s' "$GPIO_ENABLED" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on|y)
      GPIO_ENABLED="yes"
      ask GPIO_CHIP "GPIO chip" "gpiochip0"
      ask GPIO_LINE "GPIO line number"
      ;;
    *)
      GPIO_ENABLED="no"
      ;;
  esac
  ask_secret GRAFANA_ADMIN_PASSWORD "Grafana admin password (you will use this at http://localhost:16080)"

  require_value "SITE_ID" "$SITE_ID"
  require_value "Interfaces" "$INTERFACES"
  require_value "Deco LAN address" "$DECO_HOST"
  require_value "Deco admin username" "$DECO_USER"
  require_value "Deco admin password" "$DECO_PASSWORD"
  require_value "Supabase project URL" "$SUPABASE_URL"
  require_value "Supabase service role key" "$SUPABASE_KEY"
  require_value "Grafana admin password" "$GRAFANA_ADMIN_PASSWORD"
  if [ "$GPIO_ENABLED" = "yes" ]; then
    require_value "GPIO line number" "$GPIO_LINE"
  fi
}

pick_python() {
  local candidate
  for candidate in python3.14 python3.13 python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    local minor
    minor="$(python3 -c 'import sys; print(sys.version_info.minor if sys.version_info.major == 3 else -1)')"
    if [ "$minor" -ge 12 ]; then
      echo python3
      return 0
    fi
  fi
  return 1
}

write_settings() {
  export CONFIG SITE_ID DECO_HOST DECO_USER INTERFACES SUPABASE_URL
  export DECO_PASSWORD SUPABASE_KEY GPIO_ENABLED GPIO_CHIP GPIO_LINE
  export GRAFANA_ADMIN_PASSWORD
  PYTHONPATH="$REPO" "$VENV/bin/python" - <<'PY'
import os
from pathlib import Path
from scripts.setup import run_setup

run_setup(
    Path(os.environ["CONFIG"]),
    True,
    {
        "SITE_ID": os.environ["SITE_ID"],
        "DECO_HOST": os.environ["DECO_HOST"],
        "DECO_USER": os.environ["DECO_USER"],
        "INTERFACES": os.environ["INTERFACES"],
        "SUPABASE_URL": os.environ["SUPABASE_URL"],
        "DECO_PASSWORD": os.environ["DECO_PASSWORD"],
        "SUPABASE_KEY": os.environ["SUPABASE_KEY"],
        "GPIO_ENABLED": os.environ["GPIO_ENABLED"],
        "GPIO_CHIP": os.environ.get("GPIO_CHIP", "gpiochip0"),
        "GPIO_LINE": os.environ.get("GPIO_LINE", ""),
        "GRAFANA_ADMIN_PASSWORD": os.environ["GRAFANA_ADMIN_PASSWORD"],
    },
)
PY
  unset DECO_PASSWORD SUPABASE_KEY GRAFANA_ADMIN_PASSWORD
}

if [ "$STOP" -eq 1 ]; then
  stop_services
  exit 0
fi

PYTHON="$(pick_python)" || {
  echo "Python 3.12 or newer is required." >&2
  exit 1
}
echo "Using $PYTHON ($("$PYTHON" --version 2>&1))"

if [ "$RECONFIGURE" -eq 1 ] || [ ! -f "$CONFIG/netwatch.env" ]; then
  collect_settings
fi

picked_version="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
venv_version=""
if [ -x "$VENV/bin/python" ]; then
  venv_version="$("$VENV/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
fi
if [ "$venv_version" != "$picked_version" ]; then
  rm -rf "$VENV"
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --index-url https://pypi.org/simple -e "$REPO"

if [ "$RECONFIGURE" -eq 1 ] || [ ! -f "$CONFIG/netwatch.env" ]; then
  write_settings
fi

mkdir -p "$CONFIG/data" "$CONFIG/logs" "$CONFIG/run"
cat >"$CONFIG/env.sh" <<EOF
export NETWATCH_ENV="$CONFIG/netwatch.env"
export SECRETS_DIR="$CONFIG/secrets"
export DATA_DIR="$CONFIG/data"
EOF

echo "Config is in $CONFIG"
echo "Load it with: source \"$CONFIG/env.sh\""

if [ "$START" -eq 1 ]; then
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "Docker is not running." >&2
    exit 1
  fi
  stop_services
  compose_up
else
  echo "Start everything with: ./scripts/setup-local.sh --start"
fi
