"""Parse Ookla Speedtest CLI output."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeedResult:
    source: str
    download_mbps: float | None
    upload_mbps: float | None
    latency_ms: float | None
    detail_json: str


def parse_ookla(stdout: str) -> SpeedResult:
    data = json.loads(stdout)
    if isinstance(data, dict) and data.get("error"):
        raise ValueError(str(data["error"]))
    download = _bps_to_mbps(data["download"]["bandwidth"])
    upload = _bps_to_mbps(data["upload"]["bandwidth"])
    latency = data.get("ping", {}).get("latency")
    detail = {
        "server": (data.get("server") or {}).get("name"),
        "result_url": (data.get("result") or {}).get("url"),
    }
    return SpeedResult(
        "ookla",
        download,
        upload,
        None if latency is None else float(latency),
        json.dumps(detail, separators=(",", ":")),
    )


def _bps_to_mbps(bandwidth: float) -> float:
    return round(float(bandwidth) * 8 / 1_000_000, 2)
