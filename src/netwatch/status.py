"""Site reachability from rows the monitor has already stored."""

from __future__ import annotations

from datetime import datetime, timedelta

from netwatch.config import Settings
from netwatch.db import Database
from netwatch.restart.policy import Decision, Observation, decide


def current_decision(settings: Settings, db: Database, now: datetime) -> Decision:
    since = now - timedelta(seconds=settings.outage_seconds + settings.stale_seconds)
    observations = [
        Observation(recorded_at, iface, internet_ok)
        for recorded_at, iface, internet_ok in db.recent_observations(settings.site_id, since)
    ]
    return decide(
        now=now,
        interfaces=settings.interfaces,
        observations=observations,
        last_pulse_at=db.restart_state().last_pulse_at,
        gpio_enabled=settings.gpio_enabled,
        outage_seconds=settings.outage_seconds,
        cooldown_seconds=settings.cooldown_seconds,
        stale_seconds=settings.stale_seconds,
    )
