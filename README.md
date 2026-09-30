# Pi internet monitor

One repo, separate services: `monitor`, `speedtest`, `sync`, and `restart`. Grafana is the Compose profile `grafana` and runs on the Pi you keep locally. Both sites write to one Supabase project, distinguished by `SITE_ID`.

## Set up a laptop

Run `supabase/001_init.sql` once in the Supabase SQL editor, then:

```bash
./scripts/setup-local.sh
./scripts/setup-local.sh --start
```

The script asks for the site id, interfaces, Deco address and password, Supabase URL and service-role key, GPIO, and the Grafana password before it installs anything. It uses the newest installed Python that is 3.12 or newer. Config and secrets are written to `~/.netwatch`. `--start` brings the whole stack up with this repo's Compose file. Live status is at `http://localhost:16081`, the connectivity check is at `http://localhost:16081/admin`, and Grafana is at `http://localhost:16080`. Stop with `./scripts/setup-local.sh --stop`.

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

Grafana is at `http://localhost:16080` (Grafana 13.2.2, so the Infinity plugin can load). Live status, including the admin connectivity check, is at `http://localhost:16081`.

GPIO stays off until `GPIO_ENABLED=true` and `GPIO_LINE` are set. The relay is normally closed, so the pin is held low and the router stays on.

## Set up a 32-bit Pi 2

The Pi 2 does not use Docker. It runs the same five programs under systemd: monitor, speed test, sync, restart, and the status service. The live page and admin page are both on port 16081. Grafana stays on the Pi 5.

Use 32-bit Raspberry Pi OS Trixie. That release has Python 3.13 and libgpiod 2, which this install needs. Build the status page on the laptop or the Pi 5, then copy this repo to the Pi 2, including `web/dist`:

```bash
./scripts/prepare-pi2.sh
```

On the Pi 2:

```bash
sudo python3 scripts/setup.py
sudo ./scripts/install-pi2.sh
```

Do not pass `--grafana`. Give the Pi 2 its own `SITE_ID`. The Pi 5 dashboard shows this site once sync is running.

Secrets live in `/etc/netwatch/secrets` (mode `0400`). They are not written to the database or to logs.
