from datetime import timedelta

from netwatch.db import Database
from netwatch.timeutil import iso, utcnow


def test_retention_keeps_recent_unsynced_rows_and_drops_old_ones(tmp_path):
    db = Database(tmp_path / "netwatch.sqlite")
    db.migrate()
    now = utcnow()

    def iface(age_days, synced):
        moment = now - timedelta(days=age_days)
        db.insert_interface_sample(
            {
                "site_id": "site-a",
                "recorded_at": iso(moment),
                "iface": "eth0",
                "carrier": 1,
                "operstate": "up",
                "wifi_ssid": None,
                "wifi_signal_dbm": None,
                "ipv4": "192.168.68.10",
                "dns_ok": 1,
                "ping_ok": 1,
                "fetch_ok": 1,
                "internet_ok": 1,
                "probes_json": "{}",
                "synced_at": iso(moment) if synced else None,
            }
        )

    iface(3, True)
    iface(3, False)
    iface(8, False)
    db.insert_speed_sample(
        {
            "site_id": "site-a",
            "recorded_at": iso(now - timedelta(days=100)),
            "source": "ookla",
            "download_mbps": 10,
            "upload_mbps": 2,
            "latency_ms": 12,
            "detail_json": "{}",
        }
    )
    db.insert_speed_sample(
        {
            "site_id": "site-a",
            "recorded_at": iso(now - timedelta(days=10)),
            "source": "fast",
            "download_mbps": 20,
            "upload_mbps": None,
            "latency_ms": None,
            "detail_json": "{}",
        }
    )
    db.insert_restart_event(
        {
            "site_id": "site-a",
            "recorded_at": iso(now - timedelta(days=400)),
            "action": "started",
            "detail": "old",
        }
    )
    db.insert_restart_event(
        {
            "site_id": "site-a",
            "recorded_at": iso(now - timedelta(days=2)),
            "action": "released",
            "detail": "recent",
        }
    )

    db.apply_retention(
        now,
        synced_retention_seconds=48 * 3600,
        hard_retention_seconds=7 * 86400,
        speed_retention_seconds=90 * 86400,
        restart_retention_seconds=365 * 86400,
    )

    with db.connect() as conn:
        iface_rows = conn.execute("SELECT synced_at, recorded_at FROM interface_samples").fetchall()
        speeds = conn.execute("SELECT source FROM speed_samples").fetchall()
        events = conn.execute("SELECT action FROM restart_events").fetchall()

    assert len(iface_rows) == 1
    assert iface_rows[0]["synced_at"] is None
    assert [row["source"] for row in speeds] == ["fast"]
    assert [row["action"] for row in events] == ["released"]
    assert db.restart_state().pulse_in_progress is False
