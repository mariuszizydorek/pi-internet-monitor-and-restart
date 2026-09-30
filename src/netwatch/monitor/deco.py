"""Deco LAN status. The admin password is read from a secret file and never stored."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from netwatch.config import redact
from netwatch.timeutil import iso, parse_iso

log = logging.getLogger(__name__)

LOCK_NAME = "deco.lock"
LOCK_SECONDS = 2 * 3600
LOCKED_ERROR = "Deco login is locked after too many attempts. Next try uses a blank username."


@dataclass(frozen=True)
class DecoNode:
    mac: str
    name: str
    role: str
    model: str
    firmware: str
    ip: str
    inet_status: str
    group_status: str


@dataclass(frozen=True)
class DecoClient:
    mac: str
    name: str
    ip: str
    online: int
    connection: str
    up_kbps: int
    down_kbps: int
    client_type: str


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
    connect_type: str | None = None
    wan_ip: str | None = None
    wan_gateway: str | None = None
    dns_primary: str | None = None
    lan_ip: str | None = None
    nodes: tuple[DecoNode, ...] = ()
    clients: tuple[DecoClient, ...] = ()


def sign_username(username: str) -> str:
    """The Deco page hashes md5('admin' + password) when the form has no username."""
    return username.strip() or "admin"


def read_deco(host: str, username: str, password: str) -> DecoSnapshot:
    try:
        from tplink_deco_api import DecoClient
    except ImportError as exc:
        return _failed(redact(f"ImportError: {exc}", [password]))
    try:
        with DecoClient(host, sign_username(username), password) as client:
            payload = _read_forms(client)
    except Exception as exc:
        message = redact(f"{type(exc).__name__}: {exc}", [password])
        if getattr(exc, "error_code", None) == -5003:
            message = LOCKED_ERROR
        log.warning("Deco API failed: %s", message)
        return _failed(message)
    snapshot = snapshot_from_payload(payload)
    if snapshot.deco_api_ok == 0:
        log.warning("Deco API returned no status")
    return snapshot


def snapshot_from_payload(payload: dict[str, Any]) -> DecoSnapshot:
    """Build a snapshot from Deco form results. Wi-Fi and PPPoE passwords are dropped."""
    internet = payload.get("internet") or {}
    wan = ((payload.get("wan") or {}).get("wan") or {})
    ip_info = wan.get("ip_info") or {}
    lan = ((payload.get("wan") or {}).get("lan") or {}).get("ip_info") or {}
    if not lan:
        lan = (payload.get("lan") or {}).get("lan_ip") or {}
    performance = payload.get("performance") or {}
    nodes = tuple(_node(item) for item in _list(payload.get("devices"), "device_list"))
    clients = tuple(_client(item) for item in _list(payload.get("clients"), "client_list"))
    gateway = next((node for node in nodes if node.role == "master"), None)
    if gateway is None and nodes:
        gateway = nodes[0]
    ipv4 = internet.get("ipv4") or {}
    online = sum(client.online for client in clients)
    wifi = _wifi(payload.get("wlan") or {})
    detail = {
        "link_status": internet.get("link_status") or "",
        "ipv4_dial_status": ipv4.get("dial_status") or "",
        "ipv4_connect_type": wan.get("dial_type") or "",
        "wan_ip": ip_info.get("ip") or "",
        "wan_mask": ip_info.get("mask") or "",
        "wan_gateway": ip_info.get("gateway") or "",
        "dns": [ip_info.get("dns1") or "", ip_info.get("dns2") or ""],
        "lan_ip": lan.get("ip") or "",
        "lan_mask": lan.get("mask") or "",
        "wifi": wifi,
    }
    if not ipv4 and not nodes and not clients and not ip_info:
        return _failed("Deco API returned no status")
    return DecoSnapshot(
        deco_api_ok=1,
        wan_status=ipv4.get("inet_status") or None,
        client_count=online,
        cpu_usage=_float(performance.get("cpu_usage")),
        mem_usage=_float(performance.get("mem_usage")),
        model=None if gateway is None else gateway.model or None,
        firmware=None if gateway is None else gateway.firmware or None,
        detail_json=json.dumps(detail, separators=(",", ":")),
        connect_type=wan.get("dial_type") or None,
        wan_ip=ip_info.get("ip") or None,
        wan_gateway=ip_info.get("gateway") or None,
        dns_primary=ip_info.get("dns1") or None,
        lan_ip=lan.get("ip") or None,
        nodes=nodes,
        clients=clients,
    )


def login_hold_until(data_dir: Path, now: datetime) -> datetime | None:
    path = data_dir / LOCK_NAME
    if not path.is_file():
        return None
    try:
        until = parse_iso(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    return until if until > now else None


def hold_login(data_dir: Path, until: datetime) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / LOCK_NAME).write_text(iso(until), encoding="utf-8")


def clear_login_hold(data_dir: Path) -> None:
    (data_dir / LOCK_NAME).unlink(missing_ok=True)


def locked_snapshot() -> DecoSnapshot:
    return _failed(LOCKED_ERROR)


_FORMS = (
    ("wan", "admin/network", "wan_ipv4", {"operation": "read"}),
    ("lan", "admin/network", "lan_ip", {"operation": "read", "params": {"device_mac": "default"}}),
    ("internet", "admin/network", "internet", {"operation": "read"}),
    ("wlan", "admin/wireless", "wlan", {"operation": "read"}),
    ("devices", "admin/device", "device_list", {"operation": "read"}),
    (
        "clients",
        "admin/client",
        "client_list",
        {"operation": "read", "params": {"device_mac": "default"}},
    ),
)

_CONNECTIONS = {
    "band2_4": "2.4G",
    "band5": "5G",
    "band5_1": "5G",
    "band5_2": "5G",
    "band6": "6G",
    "wired": "wired",
}


def _read_forms(client: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for label, path, form, data in _FORMS:
        try:
            payload[label] = client.request(path, form, data)
        except Exception as exc:
            log.warning("Deco %s failed: %s", label, type(exc).__name__)
    try:
        performance = client.get_performance()
        payload["performance"] = {
            "cpu_usage": performance.cpu_usage,
            "mem_usage": performance.mem_usage,
        }
    except Exception as exc:
        log.warning("Deco performance failed: %s", type(exc).__name__)
    return payload


def _list(form: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(form, dict):
        return []
    items = form.get(key)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _node(item: dict[str, Any]) -> DecoNode:
    custom = str(item.get("custom_nickname") or "")
    nickname = str(item.get("nickname") or "")
    return DecoNode(
        mac=str(item.get("mac") or ""),
        name=_decoded(custom) or nickname or custom,
        role=str(item.get("role") or ""),
        model=str(item.get("device_model") or ""),
        firmware=str(item.get("software_ver") or ""),
        ip=str(item.get("device_ip") or ""),
        inet_status=str(item.get("inet_status") or ""),
        group_status=str(item.get("group_status") or ""),
    )


def _client(item: dict[str, Any]) -> DecoClient:
    wire = str(item.get("wire_type") or "")
    connection = str(item.get("connection_type") or "")
    if wire == "wired":
        label = "wired"
    else:
        label = _CONNECTIONS.get(connection, connection or wire)
    return DecoClient(
        mac=str(item.get("mac") or ""),
        name=_text(str(item.get("name") or "")),
        ip=str(item.get("ip") or ""),
        online=int(bool(item.get("online"))),
        connection=label,
        up_kbps=_int(item.get("up_speed")),
        down_kbps=_int(item.get("down_speed")),
        client_type=str(item.get("client_type") or ""),
    )


def _wifi(wlan: dict[str, Any]) -> list[dict[str, Any]]:
    bands: list[dict[str, Any]] = []
    for key, label in (("band2_4", "2.4G"), ("band5_1", "5G"), ("band5_2", "5G-2"), ("band6", "6G")):
        band = wlan.get(key)
        if not isinstance(band, dict):
            continue
        host = band.get("host") if isinstance(band.get("host"), dict) else {}
        guest = band.get("guest") if isinstance(band.get("guest"), dict) else {}
        bands.append(
            {
                "band": label,
                "ssid": _text(str(host.get("ssid") or "")),
                "enabled": int(bool(host.get("enable"))),
                "channel": host.get("channel"),
                "mode": host.get("mode") or "",
                "guest_enabled": int(bool(guest.get("enable"))),
            }
        )
    mlo = wlan.get("mlo") if isinstance(wlan.get("mlo"), dict) else {}
    mlo_host = mlo.get("host") if isinstance(mlo.get("host"), dict) else {}
    iot = wlan.get("iot") if isinstance(wlan.get("iot"), dict) else {}
    iot_host = iot.get("host") if isinstance(iot.get("host"), dict) else {}
    if mlo:
        bands.append({"band": "mlo", "enabled": int(bool(mlo_host.get("enable")))})
    if iot:
        bands.append({"band": "iot", "enabled": int(bool(iot_host.get("enable")))})
    return bands


def _text(value: str) -> str:
    if not value:
        return ""
    return _decoded(value) or value


def _decoded(value: str) -> str | None:
    if not value:
        return None
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if not decoded or any(ord(char) < 32 for char in decoded):
        return None
    return decoded


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
