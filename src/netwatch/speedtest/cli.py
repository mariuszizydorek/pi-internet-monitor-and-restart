"""Wrapper around the Ookla Speedtest CLI."""

from __future__ import annotations

import json
from collections.abc import Callable

from netwatch.monitor.commands import run_command
from netwatch.speedtest.parse import SpeedResult, parse_ookla

Runner = Callable[[list[str], float], object]

OOKLA_COMMAND = ["speedtest", "--accept-license", "--accept-gdpr", "--format=json"]


def run_ookla(runner: Runner | None = None, timeout: float = 180) -> SpeedResult:
    return _run(OOKLA_COMMAND, parse_ookla, "ookla", runner, timeout)


def _run(command: list[str], parser, source: str, runner: Runner | None, timeout: float) -> SpeedResult:
    execute = runner or run_command
    try:
        completed = execute(command, timeout)
    except Exception as exc:
        return _failed(source, str(exc))
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    code = getattr(completed, "returncode", 0)
    if code != 0:
        return _failed(source, stderr or stdout or "speed test failed")
    try:
        return parser(_json_blob(stdout))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return _failed(source, f"{exc}: {stdout.strip()[:200]}")


def _json_blob(stdout: str) -> str:
    text = stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _failed(source: str, message: str) -> SpeedResult:
    detail = json.dumps({"ok": False, "error": message.strip()[:300]}, separators=(",", ":"))
    return SpeedResult(source, None, None, None, detail)
