import time


class ReplayGuard:
    """In-memory replay guard; replace with Redis for multi-instance deploys."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def validate(self, nonce: str, timestamp: str, max_age_seconds: int) -> bool:
        now = int(time.time())
        ts = int(timestamp)
        if abs(now - ts) > max_age_seconds:
            return False

        existing = self._seen.get(nonce)
        if existing is not None and now - existing <= max_age_seconds:
            return False

        self._seen[nonce] = now
        return True
