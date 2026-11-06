"""In-process, short-lived SecretStore: the only legal home for raw values.

Contract red line (spec 0.2 "leakage and migration"):
    raw text, QR payloads, EXIF values and embedded thumbnails must never enter a
    serialisable v4 record; when a caller truly needs them, it gets an in-process
    reference into this store.

The class is therefore deliberately hostile to accidental serialisation:
1. no `__iter__` / `to_dict` / `__getstate__`, so a stray json.dump or pickle
   cannot pull plaintext into a log file;
2. `__repr__` exposes the number of entries only, never the contents, so printing
   `self` from an exception handler leaks nothing;
3. `drop()` lets the pipeline clear values as soon as they are no longer needed,
   which shortens the window in memory.
"""

from __future__ import annotations

import threading
from typing import Any


class SecretStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()

    def put(self, ref: str, value: Any) -> str:
        if not ref:
            raise ValueError("SecretStore ref must not be empty")
        with self._lock:
            self._data[ref] = value
        return ref

    def get(self, ref: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(ref, default)

    def drop(self, ref: str) -> None:
        with self._lock:
            self._data.pop(ref, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, ref: object) -> bool:
        with self._lock:
            return ref in self._data

    def __repr__(self) -> str:  # never expose contents
        return f"<SecretStore refs={len(self)}>"

    __str__ = __repr__

    def __getstate__(self) -> dict[str, Any]:
        raise TypeError("SecretStore is not serialisable (red line: no plaintext on disk)")


__all__ = ["SecretStore"]
