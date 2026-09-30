import json

from netwatch.monitor.dns import build_query, response_has_answer
from netwatch.monitor.link import parse_ipv4, parse_iw_link, parse_ping
from netwatch.monitor.probes import (
    FetchHit,
    FetchTarget,
    PingHit,
    build_report,
    check_interface,
    fetch_matches,
)
from netwatch.speedtest.parse import parse_ookla


def test_internet_requires_a_successful_fetch():
    report = build_report(
        {"google.com": True, "cloudflare.com": False, "microsoft.com": False},
        {"8.8.8.8": PingHit(True, 10.0), "1.1.1.1": PingHit(False, None)},
        {
            "google": FetchHit(False, 500, 20),
            "microsoft": FetchHit(False, None, None),
            "cloudflare": FetchHit(False, 200, 30),
        },
    )
    assert report.dns_ok is True
    assert report.ping_ok is True
    assert report.internet_ok is False

    ok = build_report(
        {"google.com": False, "cloudflare.com": False, "microsoft.com": False},
        {"8.8.8.8": PingHit(False, None), "1.1.1.1": PingHit(False, None)},
        {
            "google": FetchHit(True, 204, 40),
            "microsoft": FetchHit(False, None, None),
            "cloudflare": FetchHit(False, None, None),
        },
    )
    assert ok.internet_ok is True
    payload = json.loads(ok.probes_json)
    assert payload["fetch"]["google"]["status"] == 204


def test_fetch_body_rules():
    google = FetchTarget("google", "http://example", 204)
    microsoft = FetchTarget("microsoft", "http://example", 200, body_prefix="Microsoft Connect Test")
    cloudflare = FetchTarget("cloudflare", "https://1.1.1.1/cdn-cgi/trace", 200, body_contains="ip=")
    assert fetch_matches(204, "", google) is True
    assert fetch_matches(200, "Microsoft Connect Test", microsoft) is True
    assert fetch_matches(200, "nope", microsoft) is False
    assert fetch_matches(200, "fl=abc\nip=1.2.3.4\n", cloudflare) is True


def test_check_interface_uses_any_successful_fetch():
    report = check_interface(
        "eth0",
        resolve_system=lambda name, timeout: name == "google.com",
        resolve_direct=lambda name, server, timeout: server == "1.1.1.1",
        ping=lambda iface, host, timeout: PingHit(host == "8.8.8.8", 5.0),
        fetch=lambda iface, target, timeout: FetchHit(target.name == "microsoft", 200, 12.0),
    )
    assert report.internet_ok is True
    assert report.dns_ok is True
    assert report.ping_ok is True
    body = json.loads(report.probes_json)
    assert body["dns"]["google.com@1.1.1.1"] is True
    assert body["fetch"]["microsoft"]["ok"] is True
    assert body["fetch"]["google"]["ok"] is False


def test_link_parsers():
    assert parse_ipv4("inet 192.168.68.20/24 brd 192.168.68.255") == "192.168.68.20"
    ssid, signal = parse_iw_link("Connected to aa:bb\n\tSSID: House\n\tsignal: -48 dBm\n")
    assert (ssid, signal) == ("House", -48)
    assert parse_iw_link("Not connected.\n") == (None, None)
    ok, rtt = parse_ping(
        "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=1.2 ms\n"
        "1 packets transmitted, 1 received, 0% packet loss\n"
    )
    assert ok is True
    assert rtt == 1.2


def test_dns_answer_header():
    packet = b"\x00\x00\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
    assert response_has_answer(packet) is True
    assert response_has_answer(b"\x00\x00\x81\x83\x00\x01\x00\x01\x00\x00\x00\x00") is False
    query = build_query("google.com")
    assert query.endswith(b"\x00\x01\x00\x01")


def test_speed_parsers():
    ookla = parse_ookla(
        '{"download":{"bandwidth":12500000},"upload":{"bandwidth":2500000},'
        '"ping":{"latency":14.5},"server":{"name":"Local"}}'
    )
    assert ookla.download_mbps == 100.0
    assert ookla.upload_mbps == 20.0
    assert ookla.latency_ms == 14.5
    assert ookla.source == "ookla"
