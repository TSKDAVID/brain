from types import SimpleNamespace

import httpx
import pytest

from app.db import client


def _response(status_code: int, payload: list[dict] | dict):
    request = httpx.Request("GET", "https://supabase.test/rest/v1/demo")
    return httpx.Response(status_code=status_code, json=payload, request=request)


def _patch_settings(monkeypatch):
    monkeypatch.setattr(
        client,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://supabase.test",
            supabase_service_role_key="service-role",
        ),
    )


def test_get_rows_retries_on_transient_status(monkeypatch):
    _patch_settings(monkeypatch)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    monkeypatch.setattr(client.random, "random", lambda: 0.0)

    responses = [_response(503, {"error": "temporary"}), _response(200, [{"id": "ok"}])]
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, url: str, **_kwargs):
        calls.append((method, url))
        return responses.pop(0)

    monkeypatch.setattr(client, "_http_request", fake_request)

    result = client.get_rows("demo", "id", {"tenant_id": "tenant-1"})
    assert result == [{"id": "ok"}]
    assert len(calls) == 2


def test_get_rows_does_not_retry_on_4xx(monkeypatch):
    _patch_settings(monkeypatch)
    monkeypatch.setattr(client.time, "sleep", lambda _: None)

    calls: list[tuple[str, str]] = []

    def fake_request(method: str, url: str, **_kwargs):
        calls.append((method, url))
        return _response(400, {"error": "bad request"})

    monkeypatch.setattr(client, "_http_request", fake_request)

    with pytest.raises(httpx.HTTPStatusError):
        client.get_rows("demo", "id", {"tenant_id": "tenant-1"})

    assert len(calls) == 1
