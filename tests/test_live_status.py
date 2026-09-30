from datetime import datetime, timedelta, timezone

from netwatch.db import Database
from netwatch.localapp.snapshot import live_status
from netwatch.timeutil import iso


def test_live_status_reports_online_speed_and_connections(tmp_path):
    db = Database(tmp_path / "netwatch.sqlite")
    db.migrate()
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    db.insert_interface_sample(
        {
            "site_id": "local",
            "recorded_at": iso(now),
            "iface": "en0",
            "carrier": 1,
            "operstate": "up",
            "wifi_ssid": "House",
            "wifi_signal_dbm": -48,
            "ipv4": "192.168.68.20",
            "dns_ok": 1,
            "ping_ok": 1,
            "fetch_ok": 1,
            "internet_ok": 1,
            "probes_json": '{"dns":{"google.com":true},"ping":{"1.1.1.1":{"ok":true,"rtt_ms":8}},"fetch":{"google":{"ok":true,"status":204,"ms":40}}}',
        }
    )
    db.insert_router_check(
        {
            "site_id": "local",
            "recorded_at": iso(now),
            "gateway_ip": "192.168.68.1",
            "ping_ok": 1,
            "rtt_ms": 2.5,
            "deco_api_ok": 1,
            "wan_status": "online",
            "client_count": 4,
            "cpu_usage": 0.1,
            "mem_usage": 0.4,
            "model": "Deco",
            "firmware": "1.0",
            "detail_json": "{}",
        }
    )
    db.insert_speed_sample(
        {
            "site_id": "local",
            "recorded_at": iso(now - timedelta(hours=1)),
            "source": "ookla",
            "download_mbps": 90.5,
            "upload_mbps": 20.0,
            "latency_ms": 12.0,
            "detail_json": "{}",
        }
    )
    db.insert_restart_event(
        {
            "site_id": "local",
            "recorded_at": iso(now - timedelta(hours=3)),
            "action": "would_restart",
            "detail": "gpio off",
        }
    )

    status = live_status(
        db,
        site_id="local",
        interfaces=("en0", "wlan0"),
        now=now,
        stale_seconds=120,
    )

    assert status["overall"] == "online"
    assert status["checked_at"] == iso(now)
    en0 = status["interfaces"][0]
    assert en0["internet_ok"] is True
    assert en0["probes"]["fetch"]["google"]["status"] == 204
    assert status["interfaces"][1]["freshness"] == "unknown"
    assert status["speeds"]["ookla"]["download_mbps"] == 90.5
    assert "fast" not in status["speeds"]
    assert status["router"]["wan_status"] == "online"
    assert status["restart"]["last_event"]["action"] == "would_restart"
    assert status["speeds"]["ookla"]["error"] is None
    assert status["router"]["error"] is None


def test_live_status_shows_speed_and_router_errors(tmp_path):
    db = Database(tmp_path / "netwatch.sqlite")
    db.migrate()
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    db.insert_speed_sample(
        {
            "site_id": "local",
            "recorded_at": iso(now),
            "source": "ookla",
            "download_mbps": None,
            "upload_mbps": None,
            "latency_ms": None,
            "detail_json": '{"ok":false}',
        }
    )
    db.insert_router_check(
        {
            "site_id": "local",
            "recorded_at": iso(now),
            "gateway_ip": "192.168.68.1",
            "ping_ok": 1,
            "rtt_ms": 2.5,
            "deco_api_ok": 0,
            "wan_status": None,
            "client_count": None,
            "cpu_usage": None,
            "mem_usage": None,
            "model": None,
            "firmware": None,
            "detail_json": '{"error":"ApiError: Failed to call API: error_code=-5003"}',
        }
    )
    status = live_status(db, site_id="local", interfaces=("en0",), now=now, stale_seconds=120)
    assert status["speeds"]["ookla"]["error"] == "Speed test failed"
    assert status["router"]["error"] == "ApiError: Failed to call API: error_code=-5003"
