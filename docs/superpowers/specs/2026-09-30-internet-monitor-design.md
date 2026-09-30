# Internet monitor and router restart

This is the original design. The running system is described in [docs/architecture.md](../../architecture.md). Speed tests are Ookla only, the Pi 2 uses systemd instead of Docker, and Deco nodes and clients are stored.

One repository, separate modules. Two Raspberry Pis (one per site) run the same stack. Each row carries `SITE_ID`. One Pi also runs Grafana against the shared Supabase database.

## Modules

- `src/netwatch` — shared config, secrets, SQLite, time helpers
- `monitor` — `eth0` and `wlan0` link state, DNS, ping, HTTP fetch, Deco LAN status
- `speedtest` — Ookla CLI, then fast.com, on a slow schedule while internet is up
- `sync` — push unsynced rows to Supabase and delete expired rows locally and remotely
- `restart` — 15-minute outage rule, 2-hour cooldown, GPIO pulse
- `supabase/` — SQL for the shared database
- `grafana/` — provisioning, started with the Compose profile `grafana`
- `scripts/setup.py` — per-Pi setup, including secret files

One image, four commands. Compose runs them as separate services with `restart: unless-stopped`.

## Wiring

Both interfaces go through the Deco being power-cycled. The Pi has its own supply. The relay is normally closed: GPIO low means the router stays on. A hardware pull-down on that pin keeps the router on if the Pi loses power.

## Internet check

Per interface, in parallel:

- DNS: `google.com`, `cloudflare.com`, `microsoft.com` via the Deco, plus `google.com` against `1.1.1.1` and `8.8.8.8`
- Ping: `8.8.8.8`, `1.1.1.1`
- Fetch: Google `generate_204` (204), Microsoft `connecttest.txt` (`Microsoft Connect Test`), Cloudflare trace at `https://1.1.1.1/cdn-cgi/trace` (200)

`internet_ok` is true when at least one fetch returns the expected result. The site is offline only when every fetch fails on both interfaces.

## Restart

Pulse only when all are true:

- Both interfaces have failed every fetch for 15 continuous minutes
- The newest sample on each interface is under about 2 minutes old
- At least 2 hours have passed since the last pulse

The pulse is high for 60 seconds, then low. `GPIO_ENABLED` defaults off; the service then records `would_restart` and does not drive the pin. On process start, if a pulse was in progress, the pin is driven low before anything else.

## Deco

Ping the gateway every monitor cycle. About every 5 minutes, if a password file exists, read WAN status, client count, CPU, memory, model, and firmware from the local admin API. A failed login is stored and does not move the outage timer.

## Storage

SQLite on the Pi in WAL mode is the source of truth. Supabase is a copy.

Local retention:

- Interface and router rows: delete synced rows older than 48 hours; delete anything older than 7 days
- Speed tests: 90 days
- Restart events: 1 year

Supabase retention, applied by `sync` for this site:

- Interface and router rows: 30 days
- Speed tests and restart events: 1 year

High-rate rows are written on state change and about once a minute.

## Secrets

`/etc/netwatch/secrets/` files, mode `0400`: Deco admin password, Supabase service-role key, and on the Grafana Pi the Grafana admin password. Non-secrets (`SITE_ID`, Deco address, Supabase URL) live in `/etc/netwatch/netwatch.env`. Passwords are never written to SQLite, logs, or Supabase.

## Grafana

Compose profile `grafana` on the Pi kept locally. It calls the Supabase API with the same service-role key as `sync`, sent as the `apikey` and `Authorization` headers. Panels split series by `site_id`.
