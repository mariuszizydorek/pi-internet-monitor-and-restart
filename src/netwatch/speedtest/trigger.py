"""A file in the data directory asks the speed-test process to run now."""

from __future__ import annotations

import json
from pathlib import Path

SOURCES = ("ookla",)
SCHEDULE_NAME = "speedtest.schedule"
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 24 * 3600


class SpeedtestBusy(Exception):
    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__(source)


def _request_path(data_dir: Path) -> Path:
    return data_dir / "speedtest.request"


def _state_path(data_dir: Path) -> Path:
    return data_dir / "speedtest.state"


def read_interval(data_dir: Path, default_seconds: int) -> int:
    path = data_dir / SCHEDULE_NAME
    if not path.is_file():
        return default_seconds
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_seconds
    value = loaded.get("interval_seconds") if isinstance(loaded, dict) else None
    if isinstance(value, int) and MIN_INTERVAL_SECONDS <= value <= MAX_INTERVAL_SECONDS:
        return value
    return default_seconds


def write_interval(data_dir: Path, interval_seconds: int) -> int:
    if interval_seconds < MIN_INTERVAL_SECONDS or interval_seconds > MAX_INTERVAL_SECONDS:
        raise ValueError("interval must be between 1 minute and 24 hours")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / SCHEDULE_NAME).write_text(
        json.dumps({"interval_seconds": interval_seconds}),
        encoding="utf-8",
    )
    return interval_seconds


def request_speedtest(data_dir: Path, source: str) -> None:
    if source not in SOURCES:
        raise ValueError(source)
    data_dir.mkdir(parents=True, exist_ok=True)
    running = speedtest_view(data_dir)["running"]
    if running:
        raise SpeedtestBusy(running)
    path = _request_path(data_dir)
    try:
        fd = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise SpeedtestBusy(path.read_text(encoding="utf-8").strip() or source) from exc
    with fd:
        fd.write(source + "\n")


def take_request(data_dir: Path) -> str | None:
    path = _request_path(data_dir)
    if not path.is_file():
        return None
    source = path.read_text(encoding="utf-8").strip()
    path.unlink(missing_ok=True)
    if source not in SOURCES:
        return None
    return source


def write_running(data_dir: Path, source: str | None) -> None:
    _write_state(data_dir, running=source, error=_load_state(data_dir).get("error"))


def write_speed_error(data_dir: Path, message: str | None) -> None:
    _write_state(data_dir, running=None, error=None if message is None else message.strip()[:300])


def speedtest_view(data_dir: Path) -> dict[str, str | None]:
    loaded = _load_state(data_dir)
    running = loaded.get("running") if loaded.get("running") in SOURCES else None
    error = loaded.get("error") if isinstance(loaded.get("error"), str) and loaded.get("error") else None
    requested = None
    request = _request_path(data_dir)
    if request.is_file():
        source = request.read_text(encoding="utf-8").strip()
        if source in SOURCES:
            requested = source
    return {"running": running, "requested": requested, "error": error}


def _load_state(data_dir: Path) -> dict:
    state = _state_path(data_dir)
    if not state.is_file():
        return {}
    try:
        loaded = json.loads(state.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_state(data_dir: Path, *, running: str | None, error: str | None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _state_path(data_dir).write_text(
        json.dumps({"running": running, "error": error}),
        encoding="utf-8",
    )
