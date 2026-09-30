"""Monitor loop: both interfaces, gateway ping, and periodic Deco status."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
from datetime import datetime, timedelta

from netwatch.config import Settings, load_settings
from netwatch.db import Database
from netwatch.log import configure_logging
from netwatch.monitor.commands import (
    direct_resolver,
    http_fetch,
    ping_gateway,
    ping_host,
    system_resolver,
)
from netwatch.monitor.deco import DecoSnapshot, read_deco
from netwatch.monitor.link import LinkSnapshot, parse_ipv4, parse_iw_link, read_link
from netwatch.monitor.probes import ProbeReport, check_interface
from netwatch.timeutil import iso, utcnow

log = logging.getLogger(__name__)


def signature(link: LinkSnapshot, report: ProbeReport) -> tuple:
    return (
        link.iface,
        link.carrier,
        link.operstate,
        link.wifi_ssid,
        link.ipv4,
        report.dns_ok,
        report.ping_ok,
        report.fetch_ok,
        report.internet_ok,
    )


def should_write(
    previous: tuple | None,
    current: tuple,
    last_write: datetime | None,
    now: datetime,
    write_seconds: int,
) -> bool:
    if previous is None or last_write is None:
        return True
    if previous != current:
        return True
    return now - last_write >= timedelta(seconds=write_seconds)


def read_link_snapshot(iface: str, runner=None) -> LinkSnapshot:
    run = runner or _run
    carrier, operstate = read_link(iface)
    address = parse_ipv4(_output(run, ["ip", "-4", "addr", "show", "dev", iface]))
    ssid, signal = (None, None)
    if iface.startswith("wl"):
        ssid, signal = parse_iw_link(_output(run, ["iw", "dev", iface, "link"]))
    return LinkSnapshot(iface, carrier, operstate, ssid, signal, address)


def run_cycle(
    settings: Settings,
    db: Database,
    *,
    now: datetime | None = None,
    memory: dict | None = None,
    probe=None,
    link_reader=None,
    gateway_ping=None,
    deco_reader=None,
) -> None:
    moment = now or utcnow()
    state = memory if memory is not None else {}
    probe_fn = probe or _probe
    read_link_fn = link_reader or read_link_snapshot
    ping_fn = gateway_ping or ping_gateway
    deco_fn = deco_reader or read_deco

    for iface in settings.interfaces:
        link = read_link_fn(iface)
        report = probe_fn(iface)
        current = signature(link, report)
        key = f"iface:{iface}"
        if should_write(
            state.get(key),
            current,
            state.get(f"wrote:{iface}"),
            moment,
            settings.sample_write_seconds,
        ):
            db.insert_interface_sample(
                {
                    "site_id": settings.site_id,
                    "recorded_at": iso(moment),
                    "iface": iface,
                    "carrier": link.carrier,
                    "operstate": link.operstate,
                    "wifi_ssid": link.wifi_ssid,
                    "wifi_signal_dbm": link.wifi_signal_dbm,
                    "ipv4": link.ipv4,
                    "dns_ok": int(report.dns_ok),
                    "ping_ok": int(report.ping_ok),
                    "fetch_ok": int(report.fetch_ok),
                    "internet_ok": int(report.internet_ok),
                    "probes_json": report.probes_json,
                }
            )
            state[key] = current
            state[f"wrote:{iface}"] = moment
            log.info(
                "%s carrier=%s internet=%s",
                iface,
                link.carrier,
                int(report.internet_ok),
            )

    gateway = ping_fn(settings.deco_host, 2)
    last_deco: datetime | None = state.get("deco_at")
    due = last_deco is None or moment - last_deco >= timedelta(seconds=settings.deco_interval_seconds)
    if due:
        password = settings.secret("deco_password")
        if password:
            state["snapshot"] = deco_fn(settings.deco_host, settings.deco_user, password)
        else:
            if not state.get("deco_missing_logged"):
                log.info("Deco password file is absent; storing the gateway ping only")
                state["deco_missing_logged"] = True
        state["deco_at"] = moment
    snapshot: DecoSnapshot | None = state.get("snapshot")

    router_sig = (
        gateway.ok,
        None if snapshot is None else snapshot.wan_status,
        None if snapshot is None else snapshot.client_count,
        None if snapshot is None else snapshot.deco_api_ok,
    )
    if should_write(state.get("router"), router_sig, state.get("router_at"), moment, settings.sample_write_seconds):
        detail = "{}" if snapshot is None else snapshot.detail_json
        if snapshot is None:
            detail = json.dumps({"ping_ok": gateway.ok}, separators=(",", ":"))
        db.insert_router_check(
            {
                "site_id": settings.site_id,
                "recorded_at": iso(moment),
                "gateway_ip": settings.deco_host,
                "ping_ok": int(gateway.ok),
                "rtt_ms": gateway.rtt_ms,
                "deco_api_ok": None if snapshot is None else snapshot.deco_api_ok,
                "wan_status": None if snapshot is None else snapshot.wan_status,
                "client_count": None if snapshot is None else snapshot.client_count,
                "cpu_usage": None if snapshot is None else snapshot.cpu_usage,
                "mem_usage": None if snapshot is None else snapshot.mem_usage,
                "model": None if snapshot is None else snapshot.model,
                "firmware": None if snapshot is None else snapshot.firmware,
                "detail_json": detail,
            }
        )
        state["router"] = router_sig
        state["router_at"] = moment


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Watch Ethernet, Wi-Fi, and the Deco")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    settings = load_settings()
    db = Database(settings.database_path)
    db.migrate()
    memory: dict = {}
    while True:
        try:
            run_cycle(settings, db, memory=memory)
        except Exception:
            log.exception("monitor cycle failed")
        if args.once:
            return
        time.sleep(settings.poll_seconds)


def _probe(iface: str) -> ProbeReport:
    return check_interface(
        iface,
        resolve_system=system_resolver,
        resolve_direct=direct_resolver,
        ping=ping_host,
        fetch=http_fetch,
    )


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)


def _output(run, args: list[str]) -> str:
    try:
        completed = run(args)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout or ""
