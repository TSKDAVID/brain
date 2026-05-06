"""Redis cache abstraction with an in-process fallback.

The brain uses Redis to keep hot conversation turns, intent classifications,
runtime/parameter rows, and FAQ answers near the request path. When `REDIS_URL`
is unset (typical for local dev or unit tests), an in-memory shim with the same
small surface keeps the rest of the codebase deployment-agnostic.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Iterable, Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)


class CacheBackend(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...

    def lpush(self, key: str, *values: str) -> int: ...

    def lrange(self, key: str, start: int, end: int) -> list[str]: ...

    def ltrim(self, key: str, start: int, end: int) -> None: ...

    def expire(self, key: str, ttl_seconds: int) -> None: ...


class _InMemoryCache:
    """Thread-safe in-process cache that mirrors the Redis methods we use."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._values: dict[str, tuple[str, float | None]] = {}
        self._lists: dict[str, tuple[list[str], float | None]] = {}

    def _expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and time.monotonic() >= expires_at

    def _purge(self, key: str) -> None:
        if key in self._values and self._expired(self._values[key][1]):
            self._values.pop(key, None)
        if key in self._lists and self._expired(self._lists[key][1]):
            self._lists.pop(key, None)

    def get(self, key: str) -> str | None:
        with self._lock:
            self._purge(key)
            entry = self._values.get(key)
            return entry[0] if entry else None

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        with self._lock:
            expires_at = time.monotonic() + ttl_seconds if ttl_seconds else None
            self._values[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)
            self._lists.pop(key, None)

    def lpush(self, key: str, *values: str) -> int:
        with self._lock:
            self._purge(key)
            existing, expires_at = self._lists.get(key, ([], None))
            for value in values:
                existing.insert(0, value)
            self._lists[key] = (existing, expires_at)
            return len(existing)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        with self._lock:
            self._purge(key)
            existing = self._lists.get(key, ([], None))[0]
            if not existing:
                return []
            stop = None if end == -1 else end + 1
            return list(existing[start:stop])

    def ltrim(self, key: str, start: int, end: int) -> None:
        with self._lock:
            self._purge(key)
            entry = self._lists.get(key)
            if not entry:
                return
            existing, expires_at = entry
            stop = None if end == -1 else end + 1
            self._lists[key] = (list(existing[start:stop]), expires_at)

    def expire(self, key: str, ttl_seconds: int) -> None:
        with self._lock:
            expires_at = time.monotonic() + ttl_seconds if ttl_seconds else None
            if key in self._values:
                value, _ = self._values[key]
                self._values[key] = (value, expires_at)
            if key in self._lists:
                lst, _ = self._lists[key]
                self._lists[key] = (lst, expires_at)


class _RedisBackend:
    """Adapter around redis-py that normalizes return types to plain strings."""

    def __init__(self, url: str) -> None:
        import redis  # type: ignore

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> str | None:
        value = self._client.get(key)
        return value if value is None else str(value)

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        if ttl_seconds:
            self._client.set(name=key, value=value, ex=ttl_seconds)
        else:
            self._client.set(name=key, value=value)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def lpush(self, key: str, *values: str) -> int:
        if not values:
            return 0
        return int(self._client.lpush(key, *values))

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        return [str(item) for item in self._client.lrange(key, start, end)]

    def ltrim(self, key: str, start: int, end: int) -> None:
        self._client.ltrim(key, start, end)

    def expire(self, key: str, ttl_seconds: int) -> None:
        if ttl_seconds:
            self._client.expire(key, ttl_seconds)


_backend_singleton: CacheBackend | None = None
_singleton_lock = threading.Lock()


def get_cache() -> CacheBackend:
    """Return the process-wide cache backend, creating it lazily."""

    global _backend_singleton
    if _backend_singleton is not None:
        return _backend_singleton
    with _singleton_lock:
        if _backend_singleton is not None:
            return _backend_singleton
        url = (getattr(get_settings(), "redis_url", None) or "").strip()
        if url:
            try:
                _backend_singleton = _RedisBackend(url)
                logger.info("Redis cache enabled.")
            except Exception as exc:  # pragma: no cover - exercised in deploy
                logger.warning("Redis init failed (%s); falling back to in-memory cache.", exc)
                _backend_singleton = _InMemoryCache()
        else:
            _backend_singleton = _InMemoryCache()
        return _backend_singleton


def reset_cache_for_tests() -> None:
    """Clear the singleton so unit tests start with a fresh in-memory backend."""

    global _backend_singleton
    with _singleton_lock:
        _backend_singleton = None


def cache_get(key: str) -> str | None:
    return get_cache().get(key)


def cache_set(key: str, value: str, ttl_seconds: int | None = None) -> None:
    get_cache().set(key, value, ttl_seconds)


def cache_delete(key: str) -> None:
    get_cache().delete(key)


def cache_get_json(key: str) -> Any | None:
    raw = cache_get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        logger.debug("cache_set_json: skipping non-serializable value for %s (%s)", key, exc)
        return
    cache_set(key, encoded, ttl_seconds=ttl_seconds)


def cache_lpush(key: str, values: Iterable[str], *, ttl_seconds: int | None = None) -> int:
    backend = get_cache()
    items = list(values)
    if not items:
        return 0
    length = backend.lpush(key, *items)
    if ttl_seconds:
        backend.expire(key, ttl_seconds)
    return length


def cache_lrange(key: str, start: int = 0, end: int = -1) -> list[str]:
    return get_cache().lrange(key, start, end)


def cache_ltrim(key: str, start: int, end: int) -> None:
    get_cache().ltrim(key, start, end)
