"""Monitor loop: both interfaces, gateway ping, and periodic Deco status."""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta

from netwatch.config import Settings, load_settings
from netwatch.db import Database
from netwatch.log import configure_logging
from netwatch.monitor.active import kind_of, select_links, standby_reason
from netwatch.monitor.commands import (
    direct_resolver,
    http_fetch,
    ping_gateway,
    ping_host,
    system_resolver,
)
from netwatch.monitor.deco import (
    LOCK_SECONDS,
    DecoSnapshot,
    clear_login_hold,
    hold_login,
    locked_snapshot,
    login_hold_until,
    read_deco,
)
from netwatch.monitor.discover import discover_interfaces, up_ifaces, watch_set, write_watch
from netwatch.monitor.link import (
    LinkSnapshot,
    parse_ifconfig,
    parse_ipconfig_summary,
    parse_ipv4,
    parse_iw_link,
    read_link,
)
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


def read_link_snapshot(iface: str, runner=None, *, kind: str = "ethernet") -> LinkSnapshot:
    run = runner or _run
    if sys.platform == "darwin":
        carrier, operstate, address = parse_ifconfig(_output(run, ["ifconfig", iface]))
        ssid, signal = (None, None)
        if kind == "wifi":
            ssid, signal = parse_ipconfig_summary(_output(run, ["ipconfig", "getsummary", iface]))
        return LinkSnapshot(iface, carrier, operstate, ssid, signal, address)
    carrier, operstate = read_link(iface)
    address = parse_ipv4(_output(run, ["ip", "-4", "addr", "show", "dev", iface]))
    ssid, signal = (None, None)
    if kind == "wifi" or iface.startswith("wl"):
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
    devices: list[tuple[str, str]] | None = None,
) -> None:
    moment = now or utcnow()
    state = memory if memory is not None else {}
    probe_fn = probe or _probe
    read_link_fn = link_reader or read_link_snapshot
    ping_fn = gateway_ping or ping_gateway
    deco_fn = deco_reader or read_deco

    devices = list(devices) if devices is not None else _devices(settings)
    links = []
    for iface, kind in devices:
        link = read_link_fn(iface, kind=kind) if _accepts_kind(read_link_fn) else read_link_fn(iface)
        links.append(link)
    kinds = dict(devices)
    watched = watch_set(devices, up_ifaces(links, kinds)) or devices
    watched_names = {iface for iface, _kind in watched}
    links = [link for link in links if link.iface in watched_names]
    write_watch(settings.data_dir, watched)
    ethernet = tuple(iface for iface, kind in watched if kind == "ethernet") or settings.ethernet_ifaces
    wifi = tuple(iface for iface, kind in watched if kind == "wifi") or settings.wifi_ifaces
    probe_ifaces, _count = select_links(
        links,
        mode=settings.link_mode,
        ethernet=ethernet,
        wifi=wifi,
    )
    for link in links:
        if link.iface in probe_ifaces:
            report = probe_fn(link.iface)
        elif probe_ifaces:
            report = _standby_report(
                standby_reason(link.iface, settings.link_mode, ethernet, wifi)
            )
        else:
            report = _down_report()
        current = signature(link, report)
        key = f"iface:{link.iface}"
        if should_write(
            state.get(key),
            current,
            state.get(f"wrote:{link.iface}"),
            moment,
            settings.sample_write_seconds,
        ):
            db.insert_interface_sample(
                {
                    "site_id": settings.site_id,
                    "recorded_at": iso(moment),
                    "iface": link.iface,
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
            state[f"wrote:{link.iface}"] = moment
            if "standby" in report.probes_json:
                log.info("%s standby", link.iface)
            else:
                log.info("%s carrier=%s internet=%s", link.iface, link.carrier, int(report.internet_ok))

    gateway = ping_fn(settings.deco_host, 2)
    last_deco: datetime | None = state.get("deco_at")
    held = login_hold_until(settings.data_dir, moment)
    due = held is None and (
        last_deco is None or moment - last_deco >= timedelta(seconds=settings.deco_interval_seconds)
    )
    if held is not None and state.get("snapshot") is None:
        state["snapshot"] = locked_snapshot()
    if due:
        password = settings.secret("deco_password")
        if password:
            state["snapshot"] = deco_fn(settings.deco_host, settings.deco_user, password)
            snapshot_now: DecoSnapshot | None = state.get("snapshot")
            if snapshot_now is not None and snapshot_now.deco_api_ok == 0 and "locked" in snapshot_now.detail_json:
                hold_login(settings.data_dir, moment + timedelta(seconds=LOCK_SECONDS))
            elif snapshot_now is not None and snapshot_now.deco_api_ok == 1:
                clear_login_hold(settings.data_dir)
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


def _devices(settings: Settings) -> list[tuple[str, str]]:
    found = discover_interfaces(_run if sys.platform == "darwin" else None)
    kinds = {iface: kind for iface, kind in found}
    for iface in settings.wifi_ifaces:
        kinds[iface] = "wifi"
    for iface in settings.ethernet_ifaces:
        kinds[iface] = "ethernet"
    if not kinds:
        for iface in settings.interfaces:
            kinds[iface] = kind_of(iface, settings.ethernet_ifaces, settings.wifi_ifaces)
    return list(kinds.items())


def _accepts_kind(reader) -> bool:
    try:
        signature = inspect.signature(reader)
    except (TypeError, ValueError):
        return False
    return "kind" in signature.parameters


def _probe(iface: str) -> ProbeReport:
    return check_interface(
        iface,
        resolve_system=system_resolver,
        resolve_direct=direct_resolver,
        ping=ping_host,
        fetch=http_fetch,
    )


def _standby_report(reason: str) -> ProbeReport:
    return ProbeReport(False, False, False, False, json.dumps({"standby": reason}, separators=(",", ":")))


def _down_report() -> ProbeReport:
    return ProbeReport(False, False, False, False, json.dumps({"link": "down"}, separators=(",", ":")))


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)


def _output(run, args: list[str]) -> str:
    try:
        completed = run(args)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout or ""
