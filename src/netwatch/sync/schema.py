"""Apply the SQL files in supabase/ through the Supabase management API."""

from __future__ import annotations

from pathlib import Path

import httpx

from netwatch.config import redact


def project_ref(url: str) -> str:
    host = url.split("://", 1)[-1].split("/", 1)[0]
    return host.split(".", 1)[0]


def sql_statements(sql: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        current.append(line)
        if line.rstrip().endswith(";"):
            statement = "\n".join(current).strip()
            if statement:
                chunks.append(statement)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        chunks.append(tail)
    return chunks


def apply_sql_dir(url: str, access_token: str, sql_dir: Path, http: httpx.Client) -> list[str]:
    ref = project_ref(url)
    applied: list[str] = []
    for path in sorted(sql_dir.glob("*.sql")):
        for statement in sql_statements(path.read_text(encoding="utf-8")):
            response = http.post(
                f"https://api.supabase.com/v1/projects/{ref}/database/query",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"query": statement},
            )
            if response.status_code >= 400:
                detail = redact(response.text, [access_token])[:300]
                raise RuntimeError(f"{path.name} failed ({response.status_code}): {detail}")
        applied.append(path.name)
    return applied
