import httpx

from app.config import get_settings


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }


def get_single_row(table: str, select: str, filters: dict[str, str]) -> dict | None:
    settings = get_settings()
    query = {"select": select, "limit": "1"}
    for key, value in filters.items():
        query[key] = f"eq.{value}"

    response = httpx.get(
        f"{settings.supabase_url}/rest/v1/{table}",
        params=query,
        headers=_headers(),
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def get_rows(table: str, select: str, filters: dict[str, str], limit: int = 10) -> list[dict]:
    settings = get_settings()
    query = {"select": select, "limit": str(limit)}
    for key, value in filters.items():
        query[key] = f"eq.{value}"

    response = httpx.get(
        f"{settings.supabase_url}/rest/v1/{table}",
        params=query,
        headers=_headers(),
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def insert_row(table: str, payload: dict) -> dict | None:
    settings = get_settings()
    response = httpx.post(
        f"{settings.supabase_url}/rest/v1/{table}",
        headers={**_headers(), "Prefer": "return=representation"},
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def upsert_row(table: str, payload: dict, on_conflict: str) -> dict | None:
    settings = get_settings()
    response = httpx.post(
        f"{settings.supabase_url}/rest/v1/{table}",
        params={"on_conflict": on_conflict},
        headers={
            **_headers(),
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def update_rows(table: str, payload: dict, filters: dict[str, str]) -> list[dict]:
    settings = get_settings()
    query: dict[str, str] = {}
    for key, value in filters.items():
        query[key] = f"eq.{value}"

    response = httpx.patch(
        f"{settings.supabase_url}/rest/v1/{table}",
        params=query,
        headers={**_headers(), "Prefer": "return=representation"},
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def insert_rows_bulk(table: str, rows: list[dict], batch_size: int = 50) -> list[dict]:
    if not rows:
        return []
    settings = get_settings()
    out: list[dict] = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        response = httpx.post(
            f"{settings.supabase_url}/rest/v1/{table}",
            headers={**_headers(), "Prefer": "return=representation"},
            json=batch,
            timeout=120.0,
        )
        response.raise_for_status()
        out.extend(response.json())
    return out


def rpc_rows(function_name: str, params: dict) -> list[dict]:
    settings = get_settings()
    response = httpx.post(
        f"{settings.supabase_url}/rest/v1/rpc/{function_name}",
        headers=_headers(),
        json=params,
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def count_rows(table: str, filters: dict[str, str]) -> int:
    settings = get_settings()
    query: dict[str, str] = {"select": "id"}
    for key, value in filters.items():
        query[key] = f"eq.{value}"
    response = httpx.get(
        f"{settings.supabase_url}/rest/v1/{table}",
        params=query,
        headers={**_headers(), "Prefer": "count=exact", "Range": "0-0"},
        timeout=10.0,
    )
    response.raise_for_status()
    content_range = response.headers.get("content-range", "0-0/0")
    total = content_range.split("/")[-1]
    return int(total) if total.isdigit() else 0
