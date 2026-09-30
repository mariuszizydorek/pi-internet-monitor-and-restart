"""DNS, ping, and HTTP fetch checks for one interface."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

DNS_NAMES = ("google.com", "cloudflare.com", "microsoft.com")
PUBLIC_RESOLVERS = ("1.1.1.1", "8.8.8.8")
PING_HOSTS = ("8.8.8.8", "1.1.1.1")


@dataclass(frozen=True)
class FetchTarget:
    name: str
    url: str
    expect_status: int
    body_prefix: str = ""
    body_contains: str = ""


FETCH_TARGETS = (
    FetchTarget("google", "http://connectivitycheck.gstatic.com/generate_204", 204),
    FetchTarget(
        "microsoft",
        "http://www.msftconnecttest.com/connecttest.txt",
        200,
        body_prefix="Microsoft Connect Test",
    ),
    FetchTarget(
        "cloudflare",
        "https://1.1.1.1/cdn-cgi/trace",
        200,
        body_contains="ip=",
    ),
)


@dataclass(frozen=True)
class FetchHit:
    ok: bool
    status: int | None
    milliseconds: float | None


@dataclass(frozen=True)
class PingHit:
    ok: bool
    rtt_ms: float | None


@dataclass(frozen=True)
class ProbeReport:
    dns_ok: bool
    ping_ok: bool
    fetch_ok: bool
    internet_ok: bool
    probes_json: str


Resolver = Callable[[str, float], bool]
DirectResolver = Callable[[str, str, float], bool]
Pinger = Callable[[str, str, float], PingHit]
Fetcher = Callable[[str, FetchTarget, float], FetchHit]


def fetch_matches(status: int, body: str, target: FetchTarget) -> bool:
    if status != target.expect_status:
        return False
    if target.body_prefix and not body.startswith(target.body_prefix):
        return False
    if target.body_contains and target.body_contains not in body:
        return False
    return True


def build_report(
    dns: dict[str, bool],
    pings: dict[str, PingHit],
    fetches: dict[str, FetchHit],
) -> ProbeReport:
    system_dns = [dns[name] for name in DNS_NAMES]
    dns_ok = any(system_dns)
    ping_ok = any(hit.ok for hit in pings.values())
    fetch_ok = any(hit.ok for hit in fetches.values())
    payload = {
        "dns": dns,
        "ping": {host: {"ok": hit.ok, "rtt_ms": hit.rtt_ms} for host, hit in pings.items()},
        "fetch": {
            name: {"ok": hit.ok, "status": hit.status, "ms": hit.milliseconds}
            for name, hit in fetches.items()
        },
    }
    return ProbeReport(
        dns_ok=dns_ok,
        ping_ok=ping_ok,
        fetch_ok=fetch_ok,
        internet_ok=fetch_ok,
        probes_json=json.dumps(payload, separators=(",", ":")),
    )


def check_interface(
    iface: str,
    *,
    resolve_system: Resolver,
    resolve_direct: DirectResolver,
    ping: Pinger,
    fetch: Fetcher,
    timeout: float = 3.0,
) -> ProbeReport:
    jobs: list[tuple[str, Callable[[], object]]] = []
    for name in DNS_NAMES:
        jobs.append((f"dns:{name}", lambda name=name: resolve_system(name, timeout)))
    for server in PUBLIC_RESOLVERS:
        jobs.append(
            (
                f"dns:{DNS_NAMES[0]}@{server}",
                lambda server=server: resolve_direct(DNS_NAMES[0], server, timeout),
            )
        )
    for host in PING_HOSTS:
        jobs.append((f"ping:{host}", lambda host=host: ping(iface, host, timeout)))
    for target in FETCH_TARGETS:
        jobs.append((f"fetch:{target.name}", lambda target=target: fetch(iface, target, timeout)))

    results: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(fn): key for key, fn in jobs}
        for future, key in ((future, key) for future, key in futures.items()):
            results[key] = future.result()

    dns = {key.split(":", 1)[1]: bool(results[key]) for key in results if key.startswith("dns:")}
    pings = {key.split(":", 1)[1]: results[key] for key in results if key.startswith("ping:")}
    fetches = {key.split(":", 1)[1]: results[key] for key in results if key.startswith("fetch:")}
    return build_report(dns, pings, fetches)  # type: ignore[arg-type]
