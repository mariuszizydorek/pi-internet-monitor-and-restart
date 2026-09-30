"""Process settings and root-only secret files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised when required settings are missing."""


def read_secret(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def redact(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "***")
    return cleaned[:500]


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _deco_user() -> str:
    raw = os.environ.get("DECO_USER")
    if raw is None:
        return "admin"
    return raw.strip()


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _names(name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())


def _link_mode(raw: str) -> str:
    mode = raw.strip().lower() or "auto"
    if mode not in {"auto", "ethernet", "wifi"}:
        raise ConfigError("LINK_MODE must be auto, ethernet, or wifi")
    return mode


def _supabase_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]
    return url


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    site_id: str
    deco_host: str
    deco_user: str
    interfaces: tuple[str, ...]
    data_dir: Path
    secrets_dir: Path
    supabase_url: str
    gpio_enabled: bool
    gpio_chip: str
    gpio_line: int
    link_mode: str = "auto"
    ethernet_ifaces: tuple[str, ...] = ()
    wifi_ifaces: tuple[str, ...] = ()
    poll_seconds: int = 15
    sample_write_seconds: int = 60
    deco_interval_seconds: int = 300
    speedtest_interval_seconds: int = 6 * 3600
    speedtest_retry_seconds: int = 6 * 3600
    outage_seconds: int = 15 * 60
    cooldown_seconds: int = 2 * 3600
    stale_seconds: int = 120
    pulse_seconds: int = 60
    recovery_seconds: int = 300
    synced_retention_seconds: int = 48 * 3600
    hard_retention_seconds: int = 7 * 86400
    speed_retention_seconds: int = 90 * 86400
    restart_retention_seconds: int = 365 * 86400
    remote_sample_retention_seconds: int = 30 * 86400
    remote_speed_retention_seconds: int = 365 * 86400
    remote_restart_retention_seconds: int = 365 * 86400

    def secret(self, name: str) -> str | None:
        return read_secret(self.secrets_dir / name)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "netwatch.sqlite"


def load_settings() -> Settings:
    env_file = os.environ.get("NETWATCH_ENV", "/etc/netwatch/netwatch.env")
    load_env_file(Path(env_file))
    site_id = os.environ.get("SITE_ID", "").strip()
    if not site_id:
        raise ConfigError("SITE_ID is required")
    interfaces = tuple(
        part.strip()
        for part in os.environ.get("INTERFACES", "eth0,wlan0").split(",")
        if part.strip()
    )
    if not interfaces:
        raise ConfigError("INTERFACES must name at least one interface")
    gpio_enabled = _bool("GPIO_ENABLED", False)
    gpio_line_raw = os.environ.get("GPIO_LINE", "").strip()
    if gpio_enabled and gpio_line_raw == "":
        raise ConfigError("GPIO_LINE is required when GPIO_ENABLED is true")
    return Settings(
        site_id=site_id,
        deco_host=os.environ.get("DECO_HOST", "192.168.68.1").strip(),
        deco_user=_deco_user(),
        interfaces=interfaces,
        data_dir=Path(os.environ.get("DATA_DIR", "/data")),
        secrets_dir=Path(os.environ.get("SECRETS_DIR", "/etc/netwatch/secrets")),
        supabase_url=_supabase_url(os.environ.get("SUPABASE_URL", "")),
        gpio_enabled=gpio_enabled,
        gpio_chip=os.environ.get("GPIO_CHIP", "gpiochip0").strip() or "gpiochip0",
        gpio_line=int(gpio_line_raw) if gpio_line_raw else 0,
        link_mode=_link_mode(os.environ.get("LINK_MODE", "auto")),
        ethernet_ifaces=_names("ETHERNET_IFACES"),
        wifi_ifaces=_names("WIFI_IFACES"),
        poll_seconds=_int("MONITOR_POLL_SECONDS", 15),
        sample_write_seconds=_int("SAMPLE_WRITE_SECONDS", 60),
        deco_interval_seconds=_int("DECO_INTERVAL_SECONDS", 300),
        speedtest_interval_seconds=_int("SPEEDTEST_INTERVAL_SECONDS", 6 * 3600),
        speedtest_retry_seconds=_int("SPEEDTEST_RETRY_SECONDS", 6 * 3600),
        outage_seconds=_int("OUTAGE_SECONDS", 15 * 60),
        cooldown_seconds=_int("COOLDOWN_SECONDS", 2 * 3600),
        stale_seconds=_int("STALE_SECONDS", 120),
        pulse_seconds=_int("PULSE_SECONDS", 60),
        recovery_seconds=_int("RECOVERY_SECONDS", 300),
    )
