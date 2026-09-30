#!/bin/bash
# Install the monitor on a 32-bit Pi 2 without Docker.
# Requires 32-bit Raspberry Pi OS Trixie (Python 3.12+ and libgpiod 2).
# Build web/dist on another machine first: ./scripts/prepare-pi2.sh
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/install-pi2.sh" >&2
  exit 1
fi

arch="$(uname -m)"
if [[ "$arch" != "armv7l" && "$arch" != "armv6l" ]]; then
  echo "This installer is for a 32-bit Pi (uname -m is ${arch})." >&2
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Python 3.12 or newer is required. 32-bit Raspberry Pi OS Trixie provides it." >&2
  python3 --version >&2 || true
  exit 1
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$root/web/dist/index.html" ]]; then
  echo "web/dist is missing. On a laptop or the Pi 5 run ./scripts/prepare-pi2.sh and copy this repo again, including web/dist." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
# Raspberry Pi OS is Raspbian. Ookla has no raspbian trixie repo, and the
# packagecloud script adds one that makes every later apt update fail.
rm -f /etc/apt/sources.list.d/ookla_speedtest-cli.list \
  /etc/apt/sources.list.d/ookla_speedtest-cli.list.save
apt-get update
apt-get install -y --no-install-recommends \
  python3-venv python3-pip \
  gcc libc6-dev libffi-dev pkg-config libgpiod-dev \
  ca-certificates curl gnupg iproute2 iputils-ping iw

gpiod_version="$(pkg-config --modversion libgpiod)"
gpiod_major="${gpiod_version%%.*}"
if [[ "$gpiod_major" -lt 2 ]]; then
  echo "libgpiod ${gpiod_version} is too old. 32-bit Raspberry Pi OS Trixie provides libgpiod 2." >&2
  exit 1
fi

if ! command -v speedtest >/dev/null 2>&1; then
  deb="$(mktemp --suffix=.deb)"
  curl -fsSL -o "$deb" \
    "https://packagecloud.io/ookla/speedtest-cli/debian/pool/trixie/main/s/speedtest/speedtest_1.2.0.84-1.ea6b6773cf_armhf.deb"
  apt-get install -y "$deb"
  rm -f "$deb"
fi

install -d /opt/netwatch /var/lib/netwatch /etc/netwatch
python3 -m venv /opt/netwatch/venv
/opt/netwatch/venv/bin/pip install --upgrade pip
/opt/netwatch/venv/bin/pip install "$root"
/opt/netwatch/venv/bin/pip install gpiod

rm -rf /opt/netwatch/web/dist /opt/netwatch/supabase
mkdir -p /opt/netwatch/web /opt/netwatch/supabase
cp -a "$root/web/dist" /opt/netwatch/web/dist
cp -a "$root/supabase/." /opt/netwatch/supabase/

cat > /etc/netwatch/service.env <<'EOF'
NETWATCH_ENV=/etc/netwatch/netwatch.env
SECRETS_DIR=/etc/netwatch/secrets
DATA_DIR=/var/lib/netwatch
SQLITE_JOURNAL=wal
STATUS_DIST=/opt/netwatch/web/dist
STATUS_PORT=16081
SUPABASE_SQL_DIR=/opt/netwatch/supabase
GRAFANA_HEALTH_URL=
EOF
chmod 644 /etc/netwatch/service.env

units=(netwatch-monitor netwatch-speedtest netwatch-sync netwatch-restart netwatch-status)
for name in "${units[@]}"; do
  install -m 644 "$root/systemd/pi2/${name}.service" "/etc/systemd/system/${name}.service"
done
systemctl daemon-reload

if [[ ! -f /etc/netwatch/netwatch.env ]]; then
  echo "Packages are installed. Create config next, then start the services:" >&2
  echo "  sudo python3 scripts/setup.py" >&2
  echo "  sudo systemctl enable --now ${units[*]}" >&2
  exit 0
fi

systemctl enable --now "${units[@]}"
echo "Netwatch is running without Docker. Live page and admin: http://$(hostname -I | awk '{print $1}'):16081"
