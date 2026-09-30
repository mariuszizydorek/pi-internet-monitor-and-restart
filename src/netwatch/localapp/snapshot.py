"""Latest local readings for the status page."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from netwatch.db import Database
from netwatch.timeutil import parse_iso


def live_status(
    db: Database,
    *,
    site_id: str,
    interfaces: tuple[str, ...],
    now: datetime,
    stale_seconds: int,
) -> dict[str, Any]:
    iface_rows = [_interface(db, site_id, iface, now, stale_seconds) for iface in interfaces]
    router = _router(db, site_id, now, stale_seconds)
    speeds = {
        source: _speed(db, site_id, source) for source in ("ookla",)
    }
    event = _event(db, site_id)
    state = db.restart_state()
    checked_at = _newest(
        [row["recorded_at"] for row in iface_rows]
        + [router["recorded_at"] if router else None]
    )
    fresh = [row for row in iface_rows if row["freshness"] == "fresh" and not row["standby"]]
    if not any(row["freshness"] == "fresh" for row in iface_rows):
        overall = "unknown" if checked_at is None else "stale"
    elif not fresh:
        overall = "offline"
    elif any(row["internet_ok"] for row in fresh):
        overall = "online"
    else:
        overall = "offline"
    return {
        "site_id": site_id,
        "overall": overall,
        "checked_at": checked_at,
        "interfaces": iface_rows,
        "router": router,
        "speeds": speeds,
        "restart": {
            "last_pulse_at": None if state.last_pulse_at is None else state.last_pulse_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pulse_in_progress": state.pulse_in_progress,
            "last_event": event,
        },
    }


def _interface(db: Database, site_id: str, iface: str, now: datetime, stale_seconds: int) -> dict[str, Any]:
    row = db.latest_interface(site_id, iface)
    if row is None:
        return {
            "iface": iface,
            "recorded_at": None,
            "freshness": "unknown",
            "carrier": None,
            "operstate": None,
            "wifi_ssid": None,
            "wifi_signal_dbm": None,
            "ipv4": None,
            "dns_ok": None,
            "ping_ok": None,
            "fetch_ok": None,
            "internet_ok": None,
            "standby": None,
            "probes": {},
        }
    probes: dict[str, Any] = {}
    if row["probes_json"]:
        probes = json.loads(row["probes_json"])
    standby = probes.get("standby") if isinstance(probes.get("standby"), str) else None
    return {
        "iface": iface,
        "recorded_at": row["recorded_at"],
        "freshness": _freshness(row["recorded_at"], now, stale_seconds),
        "carrier": row["carrier"],
        "operstate": row["operstate"],
        "wifi_ssid": row["wifi_ssid"],
        "wifi_signal_dbm": row["wifi_signal_dbm"],
        "ipv4": row["ipv4"],
        "dns_ok": None if standby else bool(row["dns_ok"]),
        "ping_ok": None if standby else bool(row["ping_ok"]),
        "fetch_ok": None if standby else bool(row["fetch_ok"]),
        "internet_ok": None if standby else bool(row["internet_ok"]),
        "standby": standby,
        "probes": {} if standby else probes,
    }


def _router(db: Database, site_id: str, now: datetime, stale_seconds: int) -> dict[str, Any] | None:
    row = db.latest_router(site_id)
    if row is None:
        return None
    return {
        "recorded_at": row["recorded_at"],
        "freshness": _freshness(row["recorded_at"], now, stale_seconds),
        "gateway_ip": row["gateway_ip"],
        "ping_ok": None if row["ping_ok"] is None else bool(row["ping_ok"]),
        "rtt_ms": row["rtt_ms"],
        "deco_api_ok": None if row["deco_api_ok"] is None else bool(row["deco_api_ok"]),
        "wan_status": row["wan_status"],
        "client_count": row["client_count"],
        "cpu_usage": row["cpu_usage"],
        "mem_usage": row["mem_usage"],
        "model": row["model"],
        "firmware": row["firmware"],
        "error": _detail_error(row["detail_json"]),
    }


def _speed(db: Database, site_id: str, source: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM speed_samples
            WHERE site_id = ? AND source = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """,
            (site_id, source),
        ).fetchone()
    if row is None:
        return None
    return {
        "source": source,
        "recorded_at": row["recorded_at"],
        "download_mbps": row["download_mbps"],
        "upload_mbps": row["upload_mbps"],
        "latency_ms": row["latency_ms"],
        "error": _speed_error(row["detail_json"], row["download_mbps"]),
    }


def _event(db: Database, site_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT recorded_at, action, detail FROM restart_events
            WHERE site_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """,
            (site_id,),
        ).fetchone()
    if row is None:
        return None
    return {"recorded_at": row["recorded_at"], "action": row["action"], "detail": row["detail"]}


def _detail_error(detail_json: str | None) -> str | None:
    detail = _detail(detail_json)
    error = detail.get("error") if isinstance(detail, dict) else None
    if isinstance(error, str) and error.strip():
        return error.strip()[:300]
    return None


def _speed_error(detail_json: str | None, download_mbps: float | None) -> str | None:
    detail = _detail(detail_json)
    error = _detail_error(detail_json)
    if error:
        return error
    if isinstance(detail, dict) and detail.get("ok") is False:
        return "Speed test failed"
    if download_mbps is None and detail:
        return "Speed test failed"
    return None


def _detail(detail_json: str | None) -> dict[str, Any]:
    if not detail_json:
        return {}
    try:
        loaded = json.loads(detail_json)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _freshness(recorded_at: str, now: datetime, stale_seconds: int) -> str:
    age = (now - parse_iso(recorded_at)).total_seconds()
    if age > stale_seconds:
        return "stale"
    return "fresh"


def _newest(values: list[str | None]) -> str | None:
    present = [value for value in values if value]
    if not present:
        return None
    return max(present)
