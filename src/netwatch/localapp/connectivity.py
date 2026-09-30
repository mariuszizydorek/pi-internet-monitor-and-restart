"""Live checks for the local admin page."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from netwatch.config import Settings, redact
from netwatch.db import Database


def key_problem(api_key: str) -> str | None:
    if api_key.startswith("sbp_"):
        return (
            "That is the access token (sbp_...). The project secret key is separate "
            "and starts with sb_secret_."
        )
    if api_key.startswith("sb_publishable_"):
        return (
            "This is the publishable key. Paste the secret key instead "
            "(it starts with sb_secret_) from Project Settings, API Keys."
        )
    if api_key.startswith("eyJ"):
        role = _jwt_role(api_key)
        if role == "anon":
            return (
                "This is the anon key. Paste the service_role secret, "
                "or the new secret key that starts with sb_secret_."
            )
    return None


def check_database(database: Database, site_id: str) -> dict[str, Any]:
    try:
        database.latest_interface(site_id, "en0")
    except Exception as exc:
        return {"name": "sqlite", "ok": False, "detail": str(exc)[:300]}
    return {"name": "sqlite", "ok": True, "detail": "Local database is readable."}


def check_supabase(url: str, api_key: str, http: httpx.Client) -> dict[str, Any]:
    if not url or not api_key:
        return {
            "name": "supabase",
            "ok": False,
            "url": url,
            "detail": "SUPABASE_URL or the service role key is missing.",
        }
    problem = key_problem(api_key)
    if problem:
        return {"name": "supabase", "ok": False, "url": url, "detail": problem}
    try:
        response = http.get(
            f"{url}/rest/v1/interface_samples",
            params={"select": "site_id", "limit": "1"},
            headers={"apikey": api_key, "Authorization": f"Bearer {api_key}"},
        )
    except httpx.HTTPError as exc:
        return {
            "name": "supabase",
            "ok": False,
            "url": url,
            "detail": redact(str(exc), [api_key])[:300],
        }
    return {
        "name": "supabase",
        "ok": response.status_code == 200,
        "url": url,
        "status": response.status_code,
        "detail": _supabase_detail(response, api_key),
    }


def check_url(name: str, url: str, http: httpx.Client, ok_detail: str) -> dict[str, Any]:
    try:
        response = http.get(url)
    except httpx.HTTPError as exc:
        return {"name": name, "ok": False, "url": url, "detail": str(exc)[:300]}
    return {
        "name": name,
        "ok": response.status_code == 200,
        "url": url,
        "status": response.status_code,
        "detail": ok_detail if response.status_code == 200 else response.text[:200],
    }


def connectivity_report(
    settings: Settings,
    database: Database,
    http: httpx.Client,
    grafana_health_url: str,
) -> dict[str, Any]:
    key = settings.secret("supabase_key") or ""
    return {
        "checks": [
            check_database(database, settings.site_id),
            check_supabase(settings.supabase_url, key, http),
            check_url(http=http, name="grafana", url=grafana_health_url, ok_detail="Grafana is up."),
        ]
    }


def _supabase_detail(response: httpx.Response, api_key: str) -> str:
    if response.status_code == 200:
        return "Service role key can read interface_samples."
    if response.status_code in {401, 403}:
        if api_key.startswith("sb_secret_"):
            return "Supabase rejected the secret key. Check that it belongs to this project URL."
        return "Supabase rejected the key. Use the secret key (sb_secret_...) from Project Settings, API Keys."
    if response.status_code == 404:
        return "interface_samples is missing. Run supabase/001_init.sql in the SQL editor."
    return redact(response.text, [api_key])[:300]


def _jwt_role(token: str) -> str | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        body = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    role = body.get("role")
    return role if isinstance(role, str) else None
