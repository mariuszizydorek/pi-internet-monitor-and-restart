#!/usr/bin/env python3
"""Create per-Pi config and root-only secret files.

Run on the Pi:

    sudo python3 scripts/setup.py
    sudo python3 scripts/setup.py --grafana
"""

from __future__ import annotations

import argparse
import getpass
import os
import stat
from pathlib import Path


def prompt(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    if secret:
        value = getpass.getpass(f"{label}{suffix}: ")
    else:
        value = input(f"{label}{suffix}: ")
    value = value.strip()
    return value or default


def write_secret(directory: Path, name: str, value: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / name
    path.write_text(value.strip() + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR)
    if os.geteuid() == 0:
        os.chown(directory, 0, 0)
        os.chown(path, 0, 0)


def write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def run_setup(root: Path, grafana: bool, answers: dict[str, str]) -> None:
    site_id = answers.get("SITE_ID", "").strip()
    if not site_id:
        raise SystemExit("SITE_ID is required")
    env = {
        "SITE_ID": site_id,
        "DECO_HOST": answers.get("DECO_HOST", "192.168.68.1").strip() or "192.168.68.1",
        "DECO_USER": answers.get("DECO_USER", "admin").strip() or "admin",
        "INTERFACES": answers.get("INTERFACES", "eth0,wlan0").strip() or "eth0,wlan0",
        "SUPABASE_URL": answers.get("SUPABASE_URL", "").strip().rstrip("/"),
        "GPIO_ENABLED": "true" if answers.get("GPIO_ENABLED", "").lower() in {"1", "true", "yes", "on"} else "false",
        "GPIO_CHIP": answers.get("GPIO_CHIP", "gpiochip0").strip() or "gpiochip0",
    }
    if env["GPIO_ENABLED"] == "true":
        line = answers.get("GPIO_LINE", "").strip()
        if not line:
            raise SystemExit("GPIO_LINE is required when GPIO is enabled")
        env["GPIO_LINE"] = line
    write_env(root / "netwatch.env", env)
    secrets = root / "secrets"
    write_secret(secrets, "deco_password", answers["DECO_PASSWORD"])
    write_secret(secrets, "supabase_key", answers["SUPABASE_KEY"])
    if grafana:
        write_secret(secrets, "grafana_admin_password", answers["GRAFANA_ADMIN_PASSWORD"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Set up netwatch on this Pi")
    parser.add_argument("--root", default="/etc/netwatch", help="config directory")
    parser.add_argument("--grafana", action="store_true", help="this Pi also runs Grafana")
    args = parser.parse_args(argv)
    root = Path(args.root)
    answers = {
        "SITE_ID": prompt("SITE_ID"),
        "DECO_HOST": prompt("Deco LAN address", "192.168.68.1"),
        "DECO_USER": prompt("Deco username", "admin"),
        "INTERFACES": prompt("Interfaces", "eth0,wlan0"),
        "SUPABASE_URL": prompt("Supabase URL"),
        "DECO_PASSWORD": prompt("Deco admin password", secret=True),
        "SUPABASE_KEY": prompt("Supabase service role key", secret=True),
        "GPIO_ENABLED": prompt("Enable GPIO restart? (yes/no)", "no"),
    }
    if answers["GPIO_ENABLED"].lower() in {"1", "true", "yes", "on"}:
        answers["GPIO_CHIP"] = prompt("GPIO chip", "gpiochip0")
        answers["GPIO_LINE"] = prompt("GPIO line number")
    if args.grafana:
        answers["GRAFANA_ADMIN_PASSWORD"] = prompt("Grafana admin password", secret=True)
    run_setup(root, args.grafana, answers)
    print(f"Wrote {root / 'netwatch.env'} and secrets in {root / 'secrets'}")
    profile = " --profile grafana" if args.grafana else ""
    print(f"Start with: docker compose{profile} up -d --build")


if __name__ == "__main__":
    main()
