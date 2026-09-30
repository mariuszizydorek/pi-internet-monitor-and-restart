"""Wrapper around the Ookla Speedtest CLI."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from netwatch.speedtest.parse import SpeedResult, parse_ookla

Runner = Callable[[list[str], float], object]

OOKLA_COMMAND = ["speedtest", "--accept-license", "--accept-gdpr", "--format=json"]


def run_ookla(runner: Runner | None = None, timeout: float = 180) -> SpeedResult:
    return _run(OOKLA_COMMAND, parse_ookla, "ookla", runner or _run_ookla, timeout)


def ookla_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Ookla aborts with std::logic_error when HOME or LANG is unset."""
    env = dict(os.environ if base is None else base)
    home = env.get("HOME", "").strip()
    if not home:
        home = env.get("DATA_DIR", "").strip() or "/var/lib/netwatch"
        env["HOME"] = home
    Path(home, ".config", "ookla").mkdir(parents=True, exist_ok=True)
    if not env.get("LANG") and not env.get("LC_ALL"):
        env["LANG"] = "C.UTF-8"
    return env


def _run_ookla(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=ookla_env(),
    )


def _run(command: list[str], parser, source: str, runner: Runner | None, timeout: float) -> SpeedResult:
    execute = runner or _run_ookla
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
