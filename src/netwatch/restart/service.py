"""Restart decision loop and the 60-second GPIO pulse."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta

from netwatch.config import Settings, load_settings
from netwatch.db import Database
from netwatch.log import configure_logging
from netwatch.restart.gpio import Pin, open_pin
from netwatch.status import counted_ifaces, current_decision
from netwatch.timeutil import iso, parse_iso, utcnow

log = logging.getLogger(__name__)


def recover_pin(settings: Settings, db: Database, pin: Pin, now: datetime) -> None:
    pin.drive_low()
    if not db.restart_state().pulse_in_progress:
        return
    db.mark_pulse_finished()
    _event(
        db,
        settings,
        now,
        "pin_forced_low",
        "process started while a pulse was in progress",
    )
    log.warning("drove GPIO low because a pulse was still marked in progress")


def run_cycle(
    settings: Settings,
    db: Database,
    pin: Pin,
    *,
    now: datetime | None = None,
    sleeper=time.sleep,
    clock=utcnow,
    memory: dict | None = None,
) -> None:
    moment = now or clock()
    state = memory if memory is not None else {}
    decision = current_decision(settings, db, moment)
    if decision.action == "pulse":
        _pulse(settings, db, pin, moment, sleeper, clock)
        state["action"] = "pulse"
        return
    if decision.action in {"would_restart", "skip_cooldown", "skip_stale"} and state.get("action") != decision.action:
        detail = decision.action
        if decision.down_since is not None:
            detail = f"{decision.action} since {iso(decision.down_since)}"
        _event(db, settings, moment, decision.action, detail)
        log.info("restart %s", decision.action)
    state["action"] = decision.action


def simulate_restart(settings: Settings, db: Database, *, now: datetime | None = None) -> dict[str, str]:
    """Record what the restart policy would do. The GPIO pin is not driven."""
    moment = now or utcnow()
    decision = current_decision(settings, db, moment)
    if decision.action == "pulse":
        detail = "policy would pulse the router; pin was not driven"
    else:
        detail = f"policy says {decision.action}; pin was not driven"
    _event(db, settings, moment, "simulated", detail)
    return {"action": "simulated", "policy": decision.action, "detail": detail}


def site_recovered(settings: Settings, db: Database, now: datetime) -> bool:
    router = db.latest_router(settings.site_id)
    if router is None or not router["ping_ok"]:
        return False
    if now - parse_iso(router["recorded_at"]) > timedelta(seconds=settings.stale_seconds):
        return False
    for iface in counted_ifaces(settings, db):
        sample = db.latest_interface(settings.site_id, iface)
        if sample is None or not sample["internet_ok"] or sample["carrier"] != 1:
            return False
        if now - parse_iso(sample["recorded_at"]) > timedelta(seconds=settings.stale_seconds):
            return False
        if iface.startswith("wl") and not sample["wifi_ssid"]:
            return False
    return True


def _pulse(settings, db, pin, now, sleeper, clock) -> None:
    db.mark_pulse_started(now)
    _event(db, settings, now, "started", f"pulse for {settings.pulse_seconds}s")
    log.warning("router power cycle started")
    pin.drive_high()
    try:
        sleeper(settings.pulse_seconds)
    finally:
        pin.drive_low()
        db.mark_pulse_finished()
    released_at = clock()
    _event(db, settings, released_at, "released", "gpio low, waiting for the router")
    deadline = released_at + timedelta(seconds=settings.recovery_seconds)
    while clock() < deadline:
        if site_recovered(settings, db, clock()):
            _event(db, settings, clock(), "recovered", "ethernet, wifi, and internet are back")
            log.info("router recovered")
            return
        remaining = (deadline - clock()).total_seconds()
        sleeper(min(15, max(0, remaining)))
    _event(db, settings, clock(), "still_down", "recovery window ended before internet returned")
    log.warning("router still down after the recovery window")


def _event(db: Database, settings: Settings, moment: datetime, action: str, detail: str) -> None:
    db.insert_restart_event(
        {
            "site_id": settings.site_id,
            "recorded_at": iso(moment),
            "action": action,
            "detail": detail,
        }
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Power-cycle the router after a long outage")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    settings = load_settings()
    db = Database(settings.database_path)
    db.migrate()
    try:
        pin = open_pin(settings.gpio_enabled, settings.gpio_chip, settings.gpio_line)
    except Exception:
        log.exception("GPIO open failed; continuing without driving a pin")
        from netwatch.restart.gpio import NullPin

        pin = NullPin()
        settings = _disable_gpio(settings)
    recover_pin(settings, db, pin, utcnow())
    memory: dict = {}
    while True:
        try:
            run_cycle(settings, db, pin, memory=memory)
        except Exception:
            log.exception("restart cycle failed")
            pin.drive_low()
        if args.once:
            return
        time.sleep(settings.poll_seconds)


def _disable_gpio(settings: Settings) -> Settings:
    from dataclasses import replace

    return replace(settings, gpio_enabled=False)
