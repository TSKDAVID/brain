import logging
import random
import threading
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
DEFAULT_RETRY_ATTEMPTS = 3
BASE_RETRY_DELAY_SECONDS = 0.25


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }


def _build_url(path: str) -> str:
    settings = get_settings()
    return f"{settings.supabase_url}/rest/v1/{path}"


def _compute_retry_delay_seconds(*, attempt_index: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    exponential = BASE_RETRY_DELAY_SECONDS * (2**attempt_index)
    jitter = random.random() * 0.1
    return exponential + jitter


_shared_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_shared_client() -> httpx.Client:
    """Process-wide httpx.Client so Supabase requests reuse TCP/TLS connections."""

    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        return _shared_client
    with _client_lock:
        if _shared_client is None or _shared_client.is_closed:
            _shared_client = httpx.Client(
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=50,
                    keepalive_expiry=30.0,
                ),
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
            )
        return _shared_client


def reset_shared_client_for_tests() -> None:
    """Drop the shared client. Tests that monkeypatch httpx call this first."""

    global _shared_client
    with _client_lock:
        if _shared_client is not None:
            try:
                _shared_client.close()
            except Exception:  # pragma: no cover
                pass
        _shared_client = None


def _http_request(
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    json: Any = None,
    timeout: float = 10.0,
) -> httpx.Response:
    """Indirection over httpx so we share a connection pool and tests can patch it."""

    return _get_shared_client().request(
        method=method,
        url=url,
        params=params,
        headers=headers,
        json=json,
        timeout=timeout,
    )


def _request_with_retry(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    json: Any = None,
    timeout: float = 10.0,
    retries: int = DEFAULT_RETRY_ATTEMPTS,
) -> httpx.Response:
    attempts = max(1, retries)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = _http_request(
                method=method,
                url=_build_url(path),
                params=params,
                headers=headers,
                json=json,
                timeout=timeout,
            )
        except httpx.RequestError as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            time.sleep(_compute_retry_delay_seconds(attempt_index=attempt, retry_after=None))
            continue

        if response.status_code in TRANSIENT_STATUS_CODES and attempt < attempts - 1:
            time.sleep(
                _compute_retry_delay_seconds(
                    attempt_index=attempt,
                    retry_after=response.headers.get("Retry-After"),
                )
            )
            continue

        response.raise_for_status()
        return response

    if last_error is not None:
        raise last_error
    raise RuntimeError("Supabase request failed without response.")


def get_single_row(table: str, select: str, filters: dict[str, str]) -> dict | None:
    query = {"select": select, "limit": "1"}
    for key, value in filters.items():
        query[key] = f"eq.{value}"

    response = _request_with_retry(
        "GET",
        table,
        params=query,
        headers=_headers(),
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def get_rows(
    table: str,
    select: str,
    filters: dict[str, str],
    limit: int = 10,
    *,
    order: str | None = None,
) -> list[dict]:
    query: dict[str, str] = {"select": select, "limit": str(limit)}
    for key, value in filters.items():
        query[key] = f"eq.{value}"
    if order:
        query["order"] = order

    response = _request_with_retry(
        "GET",
        table,
        params=query,
        headers=_headers(),
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def insert_row(table: str, payload: dict) -> dict | None:
    response = _request_with_retry(
        "POST",
        table,
        headers={**_headers(), "Prefer": "return=representation"},
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def upsert_row(table: str, payload: dict, on_conflict: str) -> dict | None:
    response = _request_with_retry(
        "POST",
        table,
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
    query: dict[str, str] = {}
    for key, value in filters.items():
        query[key] = f"eq.{value}"

    response = _request_with_retry(
        "PATCH",
        table,
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
    out: list[dict] = []
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        response = _request_with_retry(
            "POST",
            table,
            headers={**_headers(), "Prefer": "return=representation"},
            json=batch,
            timeout=120.0,
        )
        response.raise_for_status()
        out.extend(response.json())
    return out


def rpc_rows(function_name: str, params: dict) -> list[dict]:
    response = _request_with_retry(
        "POST",
        f"rpc/{function_name}",
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
    query: dict[str, str] = {"select": "id"}
    for key, value in filters.items():
        query[key] = f"eq.{value}"
    response = _request_with_retry(
        "GET",
        table,
        params=query,
        headers={**_headers(), "Prefer": "count=exact", "Range": "0-0"},
        timeout=10.0,
    )
    response.raise_for_status()
    content_range = response.headers.get("content-range", "0-0/0")
    total = content_range.split("/")[-1]
    return int(total) if total.isdigit() else 0
