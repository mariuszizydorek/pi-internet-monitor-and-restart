"""Push local rows to Supabase and apply retention."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta

from netwatch.config import Settings, load_settings
from netwatch.db import SYNC_TABLES, Database
from netwatch.log import configure_logging
from netwatch.sync.client import SupabaseRest, row_for_remote
from netwatch.timeutil import iso, utcnow

log = logging.getLogger(__name__)

REMOTE_RETENTION = {
    "interface_samples": "remote_sample_retention_seconds",
    "router_checks": "remote_sample_retention_seconds",
    "speed_samples": "remote_speed_retention_seconds",
    "restart_events": "remote_restart_retention_seconds",
}


def run_cycle(settings: Settings, db: Database, rest: SupabaseRest, *, now: datetime | None = None) -> None:
    moment = now or utcnow()
    for table in SYNC_TABLES:
        rows = db.unsynced(table)
        if not rows:
            continue
        rest.insert(table, [row_for_remote(row) for row in rows])
        db.mark_synced(table, [row["id"] for row in rows], moment)
        log.info("synced %s %s rows", len(rows), table)
    db.apply_retention(
        moment,
        synced_retention_seconds=settings.synced_retention_seconds,
        hard_retention_seconds=settings.hard_retention_seconds,
        speed_retention_seconds=settings.speed_retention_seconds,
        restart_retention_seconds=settings.restart_retention_seconds,
    )
    for table, attr in REMOTE_RETENTION.items():
        cutoff = iso(moment - timedelta(seconds=getattr(settings, attr)))
        rest.delete_older(table, settings.site_id, cutoff)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync SQLite rows to Supabase")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    settings = load_settings()
    if not settings.supabase_url:
        raise SystemExit("SUPABASE_URL is required for sync")
    api_key = settings.secret("supabase_key")
    if not api_key:
        raise SystemExit("supabase_key secret file is required for sync")
    db = Database(settings.database_path)
    db.migrate()
    rest = SupabaseRest(settings.supabase_url, api_key)
    while True:
        try:
            run_cycle(settings, db, rest)
        except Exception:
            log.exception("sync cycle failed")
        if args.once:
            return
        time.sleep(60)
