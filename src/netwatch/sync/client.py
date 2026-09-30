"""Supabase PostgREST client used by the sync service."""

from __future__ import annotations

import json
from typing import Any

import httpx

_JSON_COLUMNS = {"probes_json", "detail_json"}


class SupabaseRest:
    def __init__(self, base_url: str, api_key: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._http = http or httpx.Client(timeout=30)

    def close(self) -> None:
        self._http.close()

    def insert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        response = self._http.post(
            f"{self.base_url}/rest/v1/{table}",
            params={"on_conflict": "site_id,local_id"},
            headers=self._headers("resolution=ignore-duplicates,return=minimal"),
            json=rows,
        )
        response.raise_for_status()

    def delete_older(self, table: str, site_id: str, cutoff_iso: str) -> None:
        response = self._http.delete(
            f"{self.base_url}/rest/v1/{table}",
            params={
                "site_id": f"eq.{site_id}",
                "recorded_at": f"lt.{cutoff_iso}",
            },
            headers=self._headers("return=minimal"),
        )
        response.raise_for_status()

    def _headers(self, prefer: str) -> dict[str, str]:
        return {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }


def row_for_remote(table_row: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in table_row.items() if key not in {"id", "synced_at"}}
    payload["local_id"] = table_row["id"]
    for key in _JSON_COLUMNS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            payload[key] = json.loads(value)
    return payload
