"""When a router power cycle is allowed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Observation:
    recorded_at: datetime
    iface: str
    internet_ok: bool


@dataclass(frozen=True)
class Decision:
    action: str
    down_since: datetime | None = None


def decide(
    *,
    now: datetime,
    interfaces: tuple[str, ...],
    observations: list[Observation],
    last_pulse_at: datetime | None,
    gpio_enabled: bool,
    outage_seconds: int,
    cooldown_seconds: int,
    stale_seconds: int,
) -> Decision:
    """Return up, wait, skip_stale, skip_cooldown, pulse, or would_restart."""
    latest: dict[str, Observation] = {}
    for item in observations:
        current = latest.get(item.iface)
        if current is None or item.recorded_at >= current.recorded_at:
            latest[item.iface] = item

    stale_after = timedelta(seconds=stale_seconds)
    for iface in interfaces:
        item = latest.get(iface)
        if item is None or now - item.recorded_at > stale_after:
            return Decision("skip_stale")

    if any(latest[iface].internet_ok for iface in interfaces):
        return Decision("up")

    window_start = now - timedelta(seconds=outage_seconds)
    covered = {iface: False for iface in interfaces}
    last_up: datetime | None = None
    for item in observations:
        if item.iface not in covered:
            continue
        if item.internet_ok:
            if last_up is None or item.recorded_at > last_up:
                last_up = item.recorded_at
            continue
        if item.recorded_at <= window_start:
            covered[item.iface] = True
    if not all(covered.values()):
        return Decision("wait")
    if last_up is not None and last_up > window_start:
        return Decision("wait", last_up)

    down_since = last_up or window_start
    if last_pulse_at is not None and now - last_pulse_at < timedelta(seconds=cooldown_seconds):
        return Decision("skip_cooldown", down_since)
    if not gpio_enabled:
        return Decision("would_restart", down_since)
    return Decision("pulse", down_since)
