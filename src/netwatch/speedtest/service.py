"""Run Ookla, then fast.com, while the site has internet."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta

from netwatch.config import Settings, load_settings
from netwatch.db import Database
from netwatch.log import configure_logging
from netwatch.monitor.commands import run_command
from netwatch.speedtest.parse import SpeedResult, parse_fast, parse_ookla
from netwatch.status import current_decision
from netwatch.timeutil import iso, parse_iso, utcnow

log = logging.getLogger(__name__)

OOKLA_ARGS = ["speedtest", "--accept-license", "--accept-gdpr", "--format=json"]
FAST_ARGS = ["fast", "--json"]


def due(last_at: datetime | None, now: datetime, interval_seconds: int, internet_up: bool) -> bool:
    if not internet_up:
        return False
    if last_at is None:
        return True
    return now - last_at >= timedelta(seconds=interval_seconds)


def run_tool(args: list[str], parser, timeout: float, runner=None) -> SpeedResult:
    execute = runner or run_command
    completed = execute(args, timeout)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "speed test failed").strip()
        raise RuntimeError(message[:500])
    return parser(completed.stdout)


def run_cycle(settings: Settings, db: Database, *, now: datetime | None = None, runner=None) -> None:
    moment = now or utcnow()
    decision = current_decision(settings, db, moment)
    latest = db.latest_speed(settings.site_id)
    last_at = None if latest is None else parse_iso(latest["recorded_at"])
    if not due(last_at, moment, settings.speedtest_interval_seconds, decision.action == "up"):
        log.info("speed test skipped (%s)", decision.action)
        return
    for source, args, parser in (
        ("ookla", OOKLA_ARGS, parse_ookla),
        ("fast", FAST_ARGS, parse_fast),
    ):
        try:
            result = run_tool(args, parser, timeout=120, runner=runner)
        except Exception as exc:
            log.warning("%s failed: %s", source, exc)
            result = SpeedResult(source, None, None, None, '{"ok":false}')
        db.insert_speed_sample(
            {
                "site_id": settings.site_id,
                "recorded_at": iso(moment),
                "source": result.source,
                "download_mbps": result.download_mbps,
                "upload_mbps": result.upload_mbps,
                "latency_ms": result.latency_ms,
                "detail_json": result.detail_json,
            }
        )
        log.info(
            "%s download=%s upload=%s",
            result.source,
            result.download_mbps,
            result.upload_mbps,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Ookla and fast.com on a slow schedule")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    settings = load_settings()
    db = Database(settings.database_path)
    db.migrate()
    while True:
        try:
            run_cycle(settings, db)
        except Exception:
            log.exception("speed test cycle failed")
        if args.once:
            return
        time.sleep(60)
