"""Site reachability from rows the monitor has already stored."""

from __future__ import annotations

from datetime import datetime, timedelta

from netwatch.config import Settings
from netwatch.db import Database
from netwatch.monitor.active import select_links
from netwatch.monitor.discover import read_watch
from netwatch.monitor.link import LinkSnapshot
from netwatch.restart.policy import Decision, Observation, decide


def counted_ifaces(settings: Settings, db: Database) -> tuple[str, ...]:
    watched = read_watch(settings.data_dir)
    ifaces = tuple(iface for iface, _kind in watched) or settings.interfaces
    ethernet = tuple(iface for iface, kind in watched if kind == "ethernet") or settings.ethernet_ifaces
    wifi = tuple(iface for iface, kind in watched if kind == "wifi") or settings.wifi_ifaces
    links = []
    for iface in ifaces:
        row = db.latest_interface(settings.site_id, iface)
        if row is None:
            links.append(LinkSnapshot(iface, None, None, None, None, None))
        else:
            links.append(
                LinkSnapshot(
                    iface,
                    row["carrier"],
                    row["operstate"],
                    row["wifi_ssid"],
                    row["wifi_signal_dbm"],
                    row["ipv4"],
                )
            )
    _probe, counted = select_links(
        links,
        mode=settings.link_mode,
        ethernet=ethernet,
        wifi=wifi,
    )
    return counted or ifaces


def current_decision(settings: Settings, db: Database, now: datetime) -> Decision:
    since = now - timedelta(seconds=settings.outage_seconds + settings.stale_seconds)
    observations = [
        Observation(recorded_at, iface, internet_ok)
        for recorded_at, iface, internet_ok in db.recent_observations(settings.site_id, since)
    ]
    return decide(
        now=now,
        interfaces=counted_ifaces(settings, db),
        observations=observations,
        last_pulse_at=db.restart_state().last_pulse_at,
        gpio_enabled=settings.gpio_enabled,
        outage_seconds=settings.outage_seconds,
        cooldown_seconds=settings.cooldown_seconds,
        stale_seconds=settings.stale_seconds,
    )
