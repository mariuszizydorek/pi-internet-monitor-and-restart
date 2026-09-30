"""Deco LAN status. The admin password is read from a secret file and never stored."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from netwatch.config import redact

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecoSnapshot:
    deco_api_ok: int
    wan_status: str | None
    client_count: int | None
    cpu_usage: float | None
    mem_usage: float | None
    model: str | None
    firmware: str | None
    detail_json: str


def read_deco(host: str, username: str, password: str) -> DecoSnapshot:
    try:
        from tplink_deco_api import DecoClient
    except ImportError as exc:
        return _failed(redact(f"ImportError: {exc}", [password]))
    try:
        with DecoClient(host, username, password) as client:
            internet = client.get_internet_status()
            performance = client.get_performance()
            devices = client.get_device_list()
            clients = client.get_client_list()
    except Exception as exc:
        log.warning("Deco API failed: %s", redact(f"{type(exc).__name__}: {exc}", [password]))
        return _failed(redact(f"{type(exc).__name__}: {exc}", [password]))

    gateway = next((device for device in devices if device.role == "master"), None)
    if gateway is None and devices:
        gateway = devices[0]
    online = sum(1 for client in clients if client.online)
    detail = {
        "link_status": internet.link_status,
        "ipv4_dial_status": internet.ipv4.dial_status,
        "ipv4_connect_type": internet.ipv4.connect_type,
        "ipv6_inet_status": internet.ipv6.inet_status,
    }
    return DecoSnapshot(
        deco_api_ok=1,
        wan_status=internet.ipv4.inet_status or None,
        client_count=online,
        cpu_usage=performance.cpu_usage,
        mem_usage=performance.mem_usage,
        model=None if gateway is None else gateway.device_model or None,
        firmware=None if gateway is None else gateway.software_ver or None,
        detail_json=json.dumps(detail, separators=(",", ":")),
    )


def _failed(message: str) -> DecoSnapshot:
    return DecoSnapshot(
        deco_api_ok=0,
        wan_status=None,
        client_count=None,
        cpu_usage=None,
        mem_usage=None,
        model=None,
        firmware=None,
        detail_json=json.dumps({"error": message}, separators=(",", ":")),
    )
