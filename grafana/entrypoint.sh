#!/bin/sh
# Export the Supabase API key, then start Grafana.
set -eu

read_file() {
  tr -d '\n' < "$1"
}

env_value() {
  key="$1"
  file="$2"
  grep "^${key}=" "$file" | head -n 1 | cut -d= -f2- | tr -d '"' | tr -d "'"
}

export SUPABASE_URL="$(env_value SUPABASE_URL /etc/netwatch/netwatch.env)"
export SUPABASE_KEY="$(read_file /run/secrets/supabase_key)"
export GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_admin_password

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
  echo "SUPABASE_URL and the supabase_key secret are required" >&2
  exit 1
fi

mkdir -p /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards/json
cp /opt/netwatch/provisioning/datasources/supabase.yml /etc/grafana/provisioning/datasources/supabase.yml
cp /opt/netwatch/provisioning/dashboards/dashboards.yml /etc/grafana/provisioning/dashboards/dashboards.yml
sed "s|__SUPABASE_URL__|${SUPABASE_URL}|g" \
  /opt/netwatch/provisioning/dashboards/netwatch.json \
  > /etc/grafana/provisioning/dashboards/json/netwatch.json

exec /run.sh "$@"
