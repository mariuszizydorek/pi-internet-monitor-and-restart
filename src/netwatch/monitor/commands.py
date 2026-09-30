"""Host commands used to probe a real interface."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from netwatch.monitor.dns import query_a, resolve_system
from netwatch.monitor.link import parse_ping
from netwatch.monitor.probes import FETCH_TARGETS, FetchHit, FetchTarget, PingHit


def run_command(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def ping_host(iface: str, host: str, timeout: float) -> PingHit:
    wait = max(1, int(timeout))
    try:
        completed = run_command(_ping_command(iface, host, wait), timeout + 1)
    except (OSError, subprocess.TimeoutExpired):
        return PingHit(False, None)
    ok, rtt = parse_ping(completed.stdout)
    return PingHit(ok, rtt)


def ping_gateway(host: str, timeout: float) -> PingHit:
    wait = max(1, int(timeout))
    try:
        completed = run_command(_ping_command(None, host, wait), timeout + 1)
    except (OSError, subprocess.TimeoutExpired):
        return PingHit(False, None)
    ok, rtt = parse_ping(completed.stdout)
    return PingHit(ok, rtt)


def http_fetch(iface: str, target: FetchTarget, timeout: float) -> FetchHit:
    with tempfile.TemporaryDirectory() as directory:
        body_path = Path(directory) / "body"
        try:
            completed = run_command(
                [
                    "curl",
                    "--interface",
                    iface,
                    "--max-time",
                    str(max(1, int(timeout))),
                    "--silent",
                    "--show-error",
                    "--location",
                    "--output",
                    str(body_path),
                    "--write-out",
                    "%{http_code} %{time_total}",
                    target.url,
                ],
                timeout + 1,
            )
        except (OSError, subprocess.TimeoutExpired):
            return FetchHit(False, None, None)
        parts = completed.stdout.strip().split()
        status = int(parts[0]) if parts and parts[0].isdigit() else None
        seconds = float(parts[1]) if len(parts) > 1 else None
        body = body_path.read_text(encoding="utf-8", errors="replace") if body_path.exists() else ""
        from netwatch.monitor.probes import fetch_matches

        milliseconds = None if seconds is None else round(seconds * 1000, 1)
        ok = status is not None and fetch_matches(status, body, target)
        return FetchHit(ok, status, milliseconds)


def system_resolver(name: str, timeout: float) -> bool:
    return resolve_system(name, timeout)


def direct_resolver(name: str, server: str, timeout: float) -> bool:
    return query_a(name, server, timeout)


def _ping_command(iface: str | None, host: str, wait_seconds: int) -> list[str]:
    command = ["ping", "-c", "1"]
    if sys.platform == "darwin":
        if iface:
            command.extend(["-b", iface])
        command.extend(["-W", str(wait_seconds * 1000), host])
    else:
        if iface:
            command.extend(["-I", iface])
        command.extend(["-W", str(wait_seconds), host])
    return command


def default_targets() -> tuple[FetchTarget, ...]:
    return FETCH_TARGETS
