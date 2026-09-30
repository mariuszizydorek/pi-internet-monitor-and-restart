"""Link state for Ethernet and Wi-Fi."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LinkSnapshot:
    iface: str
    carrier: int | None
    operstate: str | None
    wifi_ssid: str | None
    wifi_signal_dbm: int | None
    ipv4: str | None

    @property
    def is_wifi(self) -> bool:
        return self.iface.startswith("wl") or self.wifi_ssid is not None


def read_link(iface: str, sysfs: Path = Path("/sys/class/net")) -> tuple[int | None, str | None]:
    carrier = _read_text(sysfs / iface / "carrier")
    operstate = _read_text(sysfs / iface / "operstate")
    carrier_value: int | None
    if carrier is None:
        carrier_value = None
    elif carrier.strip() == "1":
        carrier_value = 1
    else:
        carrier_value = 0
    return carrier_value, None if operstate is None else operstate.strip() or None


def parse_ipv4(ip_addr_text: str) -> str | None:
    match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", ip_addr_text)
    return None if match is None else match.group(1)


def parse_iw_link(text: str) -> tuple[str | None, int | None]:
    if "Not connected" in text:
        return None, None
    ssid_match = re.search(r"^\s*SSID:\s*(.+)$", text, re.MULTILINE)
    signal_match = re.search(r"signal:\s*(-?\d+)\s*dBm", text)
    ssid = ssid_match.group(1).strip() if ssid_match else None
    signal = int(signal_match.group(1)) if signal_match else None
    return ssid, signal


def parse_ping(text: str) -> tuple[bool, float | None]:
    if "1 received" not in text and "1 packets received" not in text:
        # iputils prints "1 received"
        if re.search(r"\b1\s+received\b", text) is None:
            return False, None
    timing = re.search(r"time[=<]([0-9.]+)\s*ms", text)
    rtt = float(timing.group(1)) if timing else None
    return True, rtt


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
