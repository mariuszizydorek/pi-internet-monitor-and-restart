"""Local status page and JSON API."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from netwatch.config import ConfigError, load_settings, redact
from netwatch.db import Database
from netwatch.localapp.connectivity import connectivity_report
from netwatch.localapp.snapshot import live_status
from netwatch.monitor.active import kind_of
from netwatch.monitor.discover import read_watch
from netwatch.log import configure_logging, read_log_tail
from netwatch.restart.service import simulate_restart
from netwatch.speedtest.trigger import (
    SpeedtestBusy,
    read_interval,
    request_speedtest,
    speedtest_view,
    write_interval,
)
from netwatch.timeutil import utcnow

log = logging.getLogger(__name__)


def make_handler(database: Database, dist: Path | None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if path == "/api/status":
                self._status()
                return
            if path == "/api/connectivity":
                self._connectivity()
                return
            if path == "/api/speedtest/schedule":
                self._speed_schedule()
                return
            if path == "/api/logs":
                self._logs()
                return
            self._file(path)

        def do_POST(self) -> None:  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if path == "/api/speedtest":
                self._request_speedtest()
                return
            if path == "/api/speedtest/schedule":
                self._save_speed_schedule()
                return
            if path == "/api/restart/simulate":
                self._simulate_restart()
                return
            self.send_error(404)

        def _status(self) -> None:
            try:
                settings = load_settings()
                watched = read_watch(settings.data_dir)
                interfaces = tuple(iface for iface, _kind in watched) or settings.interfaces
                kinds = dict(watched)
                body = live_status(
                    database,
                    site_id=settings.site_id,
                    interfaces=interfaces,
                    now=utcnow(),
                    stale_seconds=settings.stale_seconds,
                )
                for row in body["interfaces"]:
                    row["kind"] = kinds.get(row["iface"]) or kind_of(
                        row["iface"], settings.ethernet_ifaces, settings.wifi_ifaces
                    )
                body["speedtest"] = speedtest_view(settings.data_dir)
            except (ConfigError, OSError) as exc:
                self._send_json(500, {"error": str(exc)})
                return
            self._send_json(200, body)

        def _connectivity(self) -> None:
            try:
                settings = load_settings()
                grafana_url = os.environ.get("GRAFANA_HEALTH_URL", "http://grafana:3000/api/health")
                with httpx.Client(timeout=15) as http:
                    body = connectivity_report(settings, database, http, grafana_url)
            except (ConfigError, OSError) as exc:
                self._send_json(500, {"error": str(exc)})
                return
            self._send_json(200, body)

        def _speed_schedule(self) -> None:
            try:
                settings = load_settings()
                seconds = read_interval(settings.data_dir, settings.speedtest_interval_seconds)
            except (ConfigError, OSError) as exc:
                self._send_json(500, {"error": str(exc)})
                return
            self._send_json(200, {"interval_seconds": seconds, "interval_minutes": seconds // 60})

        def _save_speed_schedule(self) -> None:
            try:
                settings = load_settings()
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                minutes = body.get("interval_minutes") if isinstance(body, dict) else None
                if isinstance(minutes, bool) or not isinstance(minutes, int):
                    raise ValueError("interval_minutes is required")
                seconds = write_interval(settings.data_dir, minutes * 60)
            except (ConfigError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"interval_seconds": seconds, "interval_minutes": seconds // 60})

        def _request_speedtest(self) -> None:
            try:
                settings = load_settings()
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b""
                source = "ookla"
                if raw:
                    body = json.loads(raw)
                    if isinstance(body, dict) and body.get("source"):
                        source = str(body["source"])
                request_speedtest(settings.data_dir, source)
            except SpeedtestBusy as exc:
                self._send_json(409, {"error": "Speed test already running", "source": exc.source})
                return
            except (ConfigError, OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(202, {"source": source})

        def _simulate_restart(self) -> None:
            try:
                settings = load_settings()
                body = simulate_restart(settings, database)
            except (ConfigError, OSError) as exc:
                self._send_json(500, {"error": str(exc)})
                return
            self._send_json(200, body)

        def _logs(self) -> None:
            try:
                settings = load_settings()
                secrets = [settings.secret("supabase_key") or "", settings.secret("deco_password") or ""]
                lines = [redact(line, secrets) for line in read_log_tail(settings.data_dir / "netwatch.log")]
            except (ConfigError, OSError) as exc:
                self._send_json(500, {"error": str(exc)})
                return
            self._send_json(200, {"lines": lines})

        def _send_json(self, status: int, body: object) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _file(self, path: str) -> None:
            if dist is None or not dist.is_dir():
                self._missing_ui()
                return
            root = dist.resolve()
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                candidate = root / "index.html"
            target = candidate if candidate.is_file() else root / "index.html"
            if not target.is_file():
                self._missing_ui()
                return
            content = target.read_bytes()
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _missing_ui(self) -> None:
            body = b"Status API is up. Build the web app with pnpm --dir web build."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            log.info("%s %s", self.address_string(), fmt % args)

    return Handler


def main() -> None:
    configure_logging()
    settings = load_settings()
    database = Database(settings.database_path)
    database.migrate()
    dist_raw = os.environ.get("STATUS_DIST", "")
    dist = Path(dist_raw) if dist_raw else None
    port = int(os.environ.get("STATUS_PORT", "16081"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(database, dist))
    log.info("status app on http://127.0.0.1:%s", port)
    server.serve_forever()
