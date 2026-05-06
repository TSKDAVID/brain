"""Test fixtures: keep in-process caches isolated between tests."""

import pytest

from app.cache import reset_cache_for_tests


@pytest.fixture(autouse=True)
def _reset_caches():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()
