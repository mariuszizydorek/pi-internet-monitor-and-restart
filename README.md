# Pi internet monitor

One repo, separate services: `monitor`, `speedtest`, `sync`, and `restart`. Grafana is the Compose profile `grafana` and runs on the Pi you keep locally. Both sites write to one Supabase project, distinguished by `SITE_ID`.

## Set up a Pi

```bash
sudo python3 scripts/setup.py
sudo python3 scripts/setup.py --grafana   # this Pi only
```

Run `supabase/001_init.sql` once in the Supabase SQL editor. Setup asks for the Supabase service role key. Sync and Grafana both use that key. There is no database username or password.

```bash
docker compose up -d --build
docker compose --profile grafana up -d --build
```

Grafana is at `http://localhost:16080`. The monitor, speed test, sync, and restart services do not listen on a port.

GPIO stays off until `GPIO_ENABLED=true` and `GPIO_LINE` are set. The relay is normally closed, so the pin is held low and the router stays on.

Secrets live in `/etc/netwatch/secrets` (mode `0400`). They are not written to the database or to logs.
