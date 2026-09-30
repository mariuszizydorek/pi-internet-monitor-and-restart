"""Run Ookla while the site has internet."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta

from netwatch.config import Settings, load_settings
from netwatch.db import Database
from netwatch.log import configure_logging
from netwatch.speedtest.cli import run_ookla
from netwatch.speedtest.trigger import read_interval, take_request, write_running, write_speed_error
from netwatch.status import current_decision
from netwatch.timeutil import iso, parse_iso, utcnow

log = logging.getLogger(__name__)

MEASURE = {
    "ookla": run_ookla,
}


def due(
    last_at: datetime | None,
    now: datetime,
    interval_seconds: int,
    internet_up: bool,
    *,
    failed: bool = False,
    retry_seconds: int = 120,
) -> bool:
    if not internet_up:
        return False
    if last_at is None:
        return True
    wait = retry_seconds if failed else interval_seconds
    return now - last_at >= timedelta(seconds=wait)


def run_cycle(settings: Settings, db: Database, *, now: datetime | None = None, runner=None) -> None:
    moment = now or utcnow()
    decision = current_decision(settings, db, moment)
    latest = db.latest_speed(settings.site_id)
    last_at = None if latest is None else parse_iso(latest["recorded_at"])
    failed = latest is not None and latest["download_mbps"] is None
    interval = read_interval(settings.data_dir, settings.speedtest_interval_seconds)
    if not due(
        last_at,
        moment,
        interval,
        decision.action == "up",
        failed=failed,
        retry_seconds=settings.speedtest_retry_seconds,
    ):
        log.info("speed test skipped (%s)", decision.action)
        if decision.action == "up":
            write_speed_error(settings.data_dir, None)
        else:
            write_speed_error(settings.data_dir, f"Speed test skipped ({decision.action})")
        return
    run_source(settings, db, "ookla", now=moment, runner=runner)


def run_source(
    settings: Settings,
    db: Database,
    source: str,
    *,
    now: datetime | None = None,
    runner=None,
) -> None:
    moment = now or utcnow()
    measure = MEASURE[source]
    write_running(settings.data_dir, source)
    try:
        result = measure(runner=runner) if runner else measure()
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
        if result.download_mbps is None:
            write_speed_error(settings.data_dir, _result_error(result.detail_json))
        else:
            write_speed_error(settings.data_dir, None)
    finally:
        write_running(settings.data_dir, None)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Ookla on a slow schedule")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    settings = load_settings()
    db = Database(settings.database_path)
    db.migrate()
    next_scheduled = 0.0
    while True:
        try:
            requested = take_request(settings.data_dir)
            if requested:
                log.info("speed test requested: %s", requested)
                run_source(settings, db, requested)
            elif time.time() >= next_scheduled:
                run_cycle(settings, db)
                next_scheduled = time.time() + 60
        except Exception as exc:
            log.exception("speed test cycle failed")
            write_speed_error(settings.data_dir, str(exc))
        if args.once:
            return
        time.sleep(5)


def _result_error(detail_json: str) -> str:
    try:
        detail = json.loads(detail_json)
    except json.JSONDecodeError:
        return "Speed test failed"
    error = detail.get("error") if isinstance(detail, dict) else None
    if isinstance(error, str) and error.strip():
        return error.strip()[:300]
    return "Speed test failed"
