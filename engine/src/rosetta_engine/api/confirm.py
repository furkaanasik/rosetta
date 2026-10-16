"""One-shot confirm tokens: the server-side half of rules 1 and 2.

Every AI operation is split into a free ``…/estimate`` that stores the exact plan under a random
token, and a run call that must present that token. A token is bound to its operation and scope
(book or job id), is used at most once and expires after ``ttl_s`` seconds.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rosetta_engine.api.errors import ApiError

DEFAULT_TTL_S = 600


@dataclass(frozen=True)
class _Entry:
    operation: str
    scope: str
    payload: Any
    expires_at: float


class ConfirmStore:
    def __init__(
        self, ttl_s: int = DEFAULT_TTL_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def issue(self, operation: str, scope: str, payload: Any) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            now = self._clock()
            self._entries = {k: v for k, v in self._entries.items() if v.expires_at > now}
            self._entries[token] = _Entry(operation, scope, payload, now + self.ttl_s)
        return token

    def take(self, token: str | None, operation: str, scope: str) -> Any:
        """Consume ``token`` for ``operation``/``scope``; 409 expired_token otherwise."""
        if not token:
            raise ApiError("expired_token", "Onay belirteci yok; önce tahmini al ve onayla")
        with self._lock:
            entry = self._entries.pop(token, None)
        if entry is None or entry.expires_at <= self._clock():
            raise ApiError(
                "expired_token", "Onay belirteci geçersiz, kullanılmış ya da süresi dolmuş"
            )
        if entry.operation != operation or entry.scope != scope:
            raise ApiError("expired_token", "Onay belirteci bu işlem için verilmedi")
        return entry.payload
