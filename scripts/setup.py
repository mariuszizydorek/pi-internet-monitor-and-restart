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
    if path.exists():
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    path.write_text(value.strip() + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
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
        "DECO_USER": "admin" if answers.get("DECO_USER") is None else answers.get("DECO_USER", "").strip(),
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


def save_supabase(root: Path, url: str, api_key: str) -> str:
    """Store the project URL and secret key. Does not require the tables to exist yet."""
    from netwatch.config import _supabase_url
    from netwatch.localapp.connectivity import key_problem

    problem = key_problem(api_key.strip())
    if problem:
        raise SystemExit(problem)
    cleaned = _supabase_url(url)
    if not cleaned.startswith("https://") or ".supabase.co" not in cleaned.split("/")[2]:
        raise SystemExit("SUPABASE_URL must look like https://YOUR-PROJECT.supabase.co")
    env_path = root / "netwatch.env"
    if not env_path.is_file():
        raise SystemExit(f"Missing {env_path}. Run the main setup first.")
    lines = []
    replaced = False
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("SUPABASE_URL="):
            lines.append(f"SUPABASE_URL={cleaned}")
            replaced = True
        else:
            lines.append(raw)
    if not replaced:
        lines.append(f"SUPABASE_URL={cleaned}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    write_secret(root / "secrets", "supabase_key", api_key)
    return cleaned


def update_supabase(root: Path, url: str, api_key: str, http=None) -> str:
    """Replace the Supabase URL and secret key, then confirm the tables can be read."""
    from netwatch.localapp.connectivity import check_supabase

    cleaned = save_supabase(root, url, api_key)
    own_client = http is None
    client = http or __import__("httpx").Client(timeout=15)
    try:
        result = check_supabase(cleaned, api_key.strip(), client)
    finally:
        if own_client:
            client.close()
    if not result["ok"]:
        raise SystemExit(result["detail"])
    return cleaned


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
        "SUPABASE_KEY": prompt("Supabase secret key (sb_secret_...)", secret=True),
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
