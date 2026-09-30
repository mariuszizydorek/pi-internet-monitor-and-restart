#!/usr/bin/env python3
"""Write Grafana config for a machine that does not run the monitor.

Asks for the Supabase project and the Grafana admin password only.
It does not ask for the Deco, GPIO, or a site id.

    sudo python3 scripts/setup-grafana.py
    sudo ./scripts/install-grafana.sh
"""

from __future__ import annotations

import argparse
import getpass
import os
import stat
from pathlib import Path


def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def prompt_secret(label: str, existing: Path) -> str:
    suffix = " [unchanged]" if existing.is_file() else ""
    value = getpass.getpass(f"{label}{suffix}: ").strip()
    if value:
        return value
    if existing.is_file():
        return existing.read_text(encoding="utf-8").strip()
    raise SystemExit(f"{label} is required")


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


def upsert_env(path: Path, updates: dict[str, str]) -> None:
    """Replace named keys and keep every other line already in the file."""
    lines: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            key = raw.split("=", 1)[0] if "=" in raw else ""
            if key in updates:
                lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                lines.append(raw)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def env_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    prefix = f"{key}="
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith(prefix):
            return raw[len(prefix) :].strip().strip("'").strip('"')
    return ""


def check_supabase_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith("/rest/v1"):
        cleaned = cleaned[: -len("/rest/v1")]
    host = cleaned.split("://", 1)[-1].split("/", 1)[0]
    if not cleaned.startswith("https://") or not host.endswith(".supabase.co"):
        raise SystemExit("Supabase URL must look like https://YOUR-PROJECT.supabase.co")
    return cleaned


def check_supabase_key(api_key: str) -> str:
    key = api_key.strip()
    if key.startswith("sbp_"):
        raise SystemExit("That is the access token (sbp_...). Paste the secret key instead.")
    if key.startswith("sb_publishable_"):
        raise SystemExit("That is the publishable key. Paste the secret key (sb_secret_...).")
    if not key:
        raise SystemExit("Supabase secret key is required")
    return key


def run_setup(root: Path, url: str, api_key: str, admin_password: str) -> None:
    upsert_env(root / "netwatch.env", {"SUPABASE_URL": check_supabase_url(url)})
    write_secret(root / "secrets", "supabase_key", check_supabase_key(api_key))
    write_secret(root / "secrets", "grafana_admin_password", admin_password.strip())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Configure Grafana without the monitor")
    parser.add_argument("--root", default="/etc/netwatch", help="config directory")
    args = parser.parse_args(argv)
    root = Path(args.root)
    env_path = root / "netwatch.env"
    secrets = root / "secrets"
    url = prompt("Supabase URL", env_value(env_path, "SUPABASE_URL"))
    api_key = prompt_secret("Supabase secret key (sb_secret_...)", secrets / "supabase_key")
    admin_password = prompt_secret("Grafana admin password", secrets / "grafana_admin_password")
    if not admin_password:
        raise SystemExit("Grafana admin password is required")
    run_setup(root, url, api_key, admin_password)
    print(f"Wrote {env_path} and secrets in {secrets}")
    print("Install Grafana with: sudo ./scripts/install-grafana.sh")


if __name__ == "__main__":
    main()
