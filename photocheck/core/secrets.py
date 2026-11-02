"""Short-lived, in-memory storage for sensitive intermediate values."""

from __future__ import annotations

import secrets
import threading
from typing import Any


class SecretStore:
    """Store values in process memory under opaque, non-guessable handles."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._lock = threading.RLock()

    def put(self, value: Any) -> str:
        token = f"secret:{secrets.token_urlsafe(24)}"
        with self._lock:
            self._values[token] = value
        return token

    def get(self, token: str) -> Any:
        with self._lock:
            try:
                return self._values[token]
            except KeyError as exc:
                raise KeyError("secret is missing or was already discarded") from exc

    def discard(self, token: str) -> bool:
        with self._lock:
            marker = object()
            return self._values.pop(token, marker) is not marker

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)

