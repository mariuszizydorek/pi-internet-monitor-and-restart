#!/bin/bash
# Install Grafana on a 64-bit Pi without Docker.
# Dashboard and Supabase datasource only. Does not install the monitor.
#
#   sudo python3 scripts/setup-grafana.py
#   sudo ./scripts/install-grafana.sh
set -euo pipefail

grafana_version="13.2.2"
deb_name="grafana_${grafana_version}_34846740809_linux_arm64.deb"
deb_url="https://dl.grafana.com/grafana/release/${grafana_version}/${deb_name}"
deb_sha256="0a8bb67d13e522747c00456ae1747f6616edac99d4a2b00c3dde073c3e8f9fe3"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/install-grafana.sh" >&2
  exit 1
fi

arch="$(uname -m)"
if [[ "$arch" != "aarch64" && "$arch" != "arm64" ]]; then
  echo "This Grafana package is for a 64-bit Pi 5 (uname -m is ${arch})." >&2
  exit 1
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
config_root="${NETWATCH_CONFIG_DIR:-/etc/netwatch}"
env_file="${config_root}/netwatch.env"
key_file="${config_root}/secrets/supabase_key"
admin_file="${config_root}/secrets/grafana_admin_password"

if [[ ! -f "$env_file" || ! -f "$key_file" || ! -f "$admin_file" ]]; then
  echo "Grafana config is missing. Run: sudo python3 scripts/setup-grafana.py" >&2
  exit 1
fi

supabase_url="$(python3 - "$env_file" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text()
for line in text.splitlines():
    if line.startswith("SUPABASE_URL="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'"))
        break
PY
)"
if [[ -z "$supabase_url" ]]; then
  echo "SUPABASE_URL is missing from ${env_file}" >&2
  exit 1
fi

if ! command -v grafana-server >/dev/null 2>&1 || ! grafana-server -v 2>/dev/null | grep -q "Version ${grafana_version}"; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends adduser libfontconfig1 musl ca-certificates curl
  deb="$(mktemp --suffix=.deb)"
  curl -fsSL -o "$deb" "$deb_url"
  echo "${deb_sha256}  ${deb}" | sha256sum -c -
  dpkg -i "$deb" || apt-get install -f -y
  rm -f "$deb"
fi

if ! id grafana >/dev/null 2>&1; then
  echo "The grafana user is missing after install." >&2
  exit 1
fi

install -d -o root -g grafana -m 755 /etc/grafana/provisioning/datasources
install -d -o root -g grafana -m 755 /etc/grafana/provisioning/dashboards/json
install -m 640 -o root -g grafana \
  "$root/grafana/provisioning/datasources/supabase.yml" \
  /etc/grafana/provisioning/datasources/supabase.yml
install -m 640 -o root -g grafana \
  "$root/grafana/provisioning/dashboards/dashboards.yml" \
  /etc/grafana/provisioning/dashboards/dashboards.yml
python3 - "$supabase_url" \
  "$root/grafana/provisioning/dashboards/netwatch.json" \
  /etc/grafana/provisioning/dashboards/json/netwatch.json <<'PY'
import pathlib, sys
url, src, dst = sys.argv[1:]
text = pathlib.Path(src).read_text()
if "__SUPABASE_URL__" not in text:
    raise SystemExit("dashboard template is missing __SUPABASE_URL__")
path = pathlib.Path(dst)
path.write_text(text.replace("__SUPABASE_URL__", url))
path.chmod(0o640)
PY
chown root:grafana /etc/grafana/provisioning/dashboards/json/netwatch.json

umask 077
install -d -m 755 /etc/grafana
python3 - "$supabase_url" "$key_file" /etc/grafana/netwatch.env <<'PY'
import pathlib, sys
url, key_path, dest = sys.argv[1:]
key = pathlib.Path(key_path).read_text().strip()
path = pathlib.Path(dest)
path.write_text(f"SUPABASE_URL={url}\nSUPABASE_KEY={key}\n")
path.chmod(0o600)
PY
install -m 640 -o root -g grafana "$admin_file" /etc/grafana/admin_password

install -d /etc/systemd/system/grafana-server.service.d
cat > /etc/systemd/system/grafana-server.service.d/netwatch.conf <<'EOF'
[Service]
EnvironmentFile=/etc/grafana/netwatch.env
Environment=GF_SERVER_HTTP_PORT=16080
Environment=GF_USERS_ALLOW_SIGN_UP=false
Environment=GF_SECURITY_ADMIN_PASSWORD__FILE=/etc/grafana/admin_password
EOF

grafana-cli plugins install yesoreyeram-infinity-datasource
systemctl daemon-reload
systemctl enable grafana-server
systemctl restart grafana-server
echo "Grafana is running without Docker. Open http://$(hostname -I | awk '{print $1}'):16080"
