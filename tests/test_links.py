import json
from datetime import datetime, timezone

from netwatch.config import Settings
from netwatch.db import Database
from netwatch.monitor.active import select_links
from netwatch.monitor.discover import discover_sysfs, parse_hardware_ports, read_watch, watch_set
from netwatch.monitor.link import LinkSnapshot, parse_ifconfig, parse_ipconfig_summary
from netwatch.monitor.probes import ProbeReport
from netwatch.monitor.service import run_cycle
from netwatch.status import counted_ifaces


PORTS = """
Hardware Port: Ethernet Adapter (en4)
Device: en4

Hardware Port: Thunderbolt Bridge
Device: bridge0

Hardware Port: Wi-Fi
Device: en0

Hardware Port: Thunderbolt 1
Device: en1
"""


def test_hardware_ports_keep_wifi_and_ethernet_only():
    assert parse_hardware_ports(PORTS) == [("en4", "ethernet"), ("en0", "wifi")]


def test_sysfs_splits_ethernet_and_wifi(tmp_path):
    eth = tmp_path / "eth0"
    wifi = tmp_path / "wlan0"
    docker = tmp_path / "docker0"
    for path in (eth, wifi, docker):
        path.mkdir()
    (eth / "type").write_text("1")
    (eth / "device").mkdir()
    (wifi / "wireless").mkdir()
    (wifi / "type").write_text("1")
    (docker / "type").write_text("1")
    assert discover_sysfs(tmp_path) == [("eth0", "ethernet"), ("wlan0", "wifi")]


def test_laptop_on_wifi_hides_unused_ethernet_adapters():
    devices = [("en0", "wifi"), ("en4", "ethernet"), ("en5", "ethernet")]
    assert watch_set(devices, {"en0"}) == [("en0", "wifi")]


def test_pi_keeps_a_down_port_and_uses_whichever_links_are_up():
    devices = [("eth0", "ethernet"), ("wlan0", "wifi")]
    assert watch_set(devices, {"wlan0"}) == [("eth0", "ethernet"), ("wlan0", "wifi")]
    assert watch_set(devices, {"eth0", "wlan0"}) == [("eth0", "ethernet"), ("wlan0", "wifi")]


def test_auto_probes_every_link_that_is_up():
    links = [
        LinkSnapshot("eth0", 1, "up", None, None, "192.168.68.10"),
        LinkSnapshot("wlan0", 1, "up", "House", -40, "192.168.68.11"),
    ]
    probe, counted = select_links(links, mode="auto", ethernet=("eth0",), wifi=("wlan0",))
    assert probe == ("eth0", "wlan0")
    assert counted == probe


def test_speed_schedule_file_overrides_the_env_interval(tmp_path):
    from netwatch.speedtest.trigger import read_interval, write_interval

    assert read_interval(tmp_path, 300) == 300
    assert write_interval(tmp_path, 3600) == 3600
    assert read_interval(tmp_path, 300) == 3600
    try:
        write_interval(tmp_path, 30)
    except ValueError as exc:
        assert "1 minute" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_due_waits_five_minutes_or_two_after_a_failure():
    from datetime import timedelta

    from netwatch.speedtest.service import due

    now = datetime(2026, 9, 30, 12, 10, tzinfo=timezone.utc)
    assert due(now - timedelta(minutes=4), now, 300, True) is False
    assert due(now - timedelta(minutes=5), now, 300, True) is True
    assert due(now - timedelta(minutes=3), now, 300, True, failed=True, retry_seconds=120) is True
    assert due(now - timedelta(minutes=1), now, 300, True, failed=True, retry_seconds=120) is False


def test_ping_uses_the_platform_interface_flag(monkeypatch):
    from netwatch.monitor import commands

    monkeypatch.setattr(commands.sys, "platform", "darwin")
    assert commands._ping_command("en0", "1.1.1.1", 2) == ["ping", "-c", "1", "-b", "en0", "-W", "2000", "1.1.1.1"]
    monkeypatch.setattr(commands.sys, "platform", "linux")
    assert commands._ping_command("eth0", "1.1.1.1", 2) == ["ping", "-c", "1", "-I", "eth0", "-W", "2", "1.1.1.1"]


def test_macos_link_text_reads_wifi():
    carrier, operstate, address = parse_ifconfig("en0: flags=8863<UP,RUNNING>\n\tinet 192.168.68.20 netmask 0xffff0000\n\tstatus: active\n")
    assert (carrier, operstate, address) == (1, "up", "192.168.68.20")
    ssid, signal = parse_ipconfig_summary("LinkStatusActive : TRUE\nSSID : House\nagrCtlRSSI : -48\n")
    assert (ssid, signal) == ("House", -48)
    hidden, _signal = parse_ipconfig_summary("SSID : <redacted>\n")
    assert hidden == "connected"


def test_cycle_records_wifi_and_leaves_the_idle_port_unprobed(tmp_path):
    db = Database(tmp_path / "netwatch.sqlite")
    db.migrate()
    settings = Settings(
        site_id="local",
        deco_host="192.168.68.1",
        deco_user="admin",
        interfaces=("en0",),
        data_dir=tmp_path,
        secrets_dir=tmp_path,
        supabase_url="",
        gpio_enabled=False,
        gpio_chip="gpiochip0",
        gpio_line=0,
    )
    probed = []

    def reader(iface, runner=None, *, kind="ethernet"):
        del runner, kind
        if iface == "en0":
            return LinkSnapshot("en0", 1, "up", "House", -48, "192.168.68.20")
        return LinkSnapshot("eth0", 0, "down", None, None, None)

    def probe(iface):
        probed.append(iface)
        return ProbeReport(True, True, True, True, "{}")

    run_cycle(
        settings,
        db,
        now=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
        probe=probe,
        link_reader=reader,
        gateway_ping=lambda host, timeout: type("Hit", (), {"ok": True, "rtt_ms": 1.0})(),
        deco_reader=lambda *args: None,
        devices=[("en0", "wifi"), ("eth0", "ethernet")],
    )
    assert probed == ["en0"]
    assert read_watch(tmp_path) == [("eth0", "ethernet"), ("en0", "wifi")]
    row = db.latest_interface("local", "en0")
    assert row["wifi_ssid"] == "House"
    assert row["internet_ok"] == 1
    idle = db.latest_interface("local", "eth0")
    assert json.loads(idle["probes_json"])["standby"] == "not connected"
    assert counted_ifaces(settings, db) == ("en0",)
