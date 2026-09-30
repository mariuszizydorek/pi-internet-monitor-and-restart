"""Find the Ethernet and Wi-Fi interfaces this machine can actually use."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from netwatch.monitor.link import LinkSnapshot

PRIMARY = {"eth0", "end0", "wlan0"}
_SKIP_PREFIXES = (
    "lo",
    "docker",
    "veth",
    "br-",
    "virbr",
    "tun",
    "tap",
    "dummy",
    "bond",
    "gre",
    "sit",
    "ifb",
    "wg",
    "tailscale",
    "zt",
)


def parse_hardware_ports(text: str) -> list[tuple[str, str]]:
    """Read `networksetup -listallhardwareports` into (iface, kind) pairs."""
    port = ""
    found: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Hardware Port:"):
            port = line.split(":", 1)[1].strip().lower()
            continue
        if not line.startswith("Device:"):
            continue
        iface = line.split(":", 1)[1].strip()
        kind = _port_kind(port)
        if iface and kind:
            found.append((iface, kind))
        port = ""
    return found


def discover_sysfs(sysfs: Path) -> list[tuple[str, str]]:
    if not sysfs.is_dir():
        return []
    found: list[tuple[str, str]] = []
    for entry in sorted(sysfs.iterdir()):
        name = entry.name
        if name == "lo" or name.startswith(_SKIP_PREFIXES):
            continue
        wireless = (entry / "wireless").exists() or (entry / "phy80211").exists()
        if wireless or name.startswith(("wl", "wifi")):
            found.append((name, "wifi"))
            continue
        type_text = _read(entry / "type")
        physical = (entry / "device").exists() or name.startswith(("eth", "end", "enp", "eno"))
        if type_text == "1" and physical:
            found.append((name, "ethernet"))
    return found


def watch_set(devices: list[tuple[str, str]], up: set[str]) -> list[tuple[str, str]]:
    """Keep links that are up.

    A single Ethernet port or Wi-Fi radio is kept even when it is down, so a
    Pi still shows the unused port. Extra adapters that are all down (a laptop
    with several unused USB Ethernet devices) are left off the page.
    """
    grouped: dict[str, list[str]] = {"ethernet": [], "wifi": []}
    for iface, kind in devices:
        if kind in grouped:
            grouped[kind].append(iface)
    chosen: list[tuple[str, str]] = []
    for kind, names in grouped.items():
        alive = [name for name in names if name in up]
        if alive:
            chosen.extend((name, kind) for name in alive)
            continue
        if len(names) == 1:
            chosen.append((names[0], kind))
            continue
        primary = [name for name in names if name in PRIMARY or (kind == "wifi" and name.startswith("wl"))]
        chosen.extend((name, kind) for name in primary)
    return chosen


def write_watch(data_dir: Path, devices: list[tuple[str, str]]) -> None:
    payload = {
        "interfaces": [{"iface": iface, "kind": kind} for iface, kind in devices],
    }
    path = data_dir / "links.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def read_watch(data_dir: Path) -> list[tuple[str, str]]:
    path = data_dir / "links.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    rows = payload.get("interfaces") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    found: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        iface = str(row.get("iface", "")).strip()
        kind = str(row.get("kind", "")).strip()
        if iface and kind in {"ethernet", "wifi"}:
            found.append((iface, kind))
    return found


def up_ifaces(links: list[LinkSnapshot], kinds: dict[str, str]) -> set[str]:
    from netwatch.monitor.active import link_is_up

    return {link.iface for link in links if link_is_up(link, kinds.get(link.iface, "ethernet"))}


def discover_interfaces(runner=None, sysfs: Path | None = None) -> list[tuple[str, str]]:
    if sys.platform == "darwin" and runner is not None:
        try:
            completed = runner(["networksetup", "-listallhardwareports"])
        except (OSError, TimeoutError):
            return []
        return parse_hardware_ports(getattr(completed, "stdout", "") or "")
    return discover_sysfs(sysfs or Path("/sys/class/net"))


def _port_kind(port: str) -> str | None:
    if "wi-fi" in port or "wifi" in port or "airport" in port:
        return "wifi"
    if port.startswith("ethernet"):
        return "ethernet"
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
