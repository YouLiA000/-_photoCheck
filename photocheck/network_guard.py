"""Process-local network guard used by the offline validation smoke test."""

from __future__ import annotations

import socket
from typing import Any


class NetworkAccessBlocked(OSError):
    """Raised when code attempts a network connection under the offline guard."""


class OfflineGuard:
    def __init__(self) -> None:
        self._socket_connect = socket.socket.connect
        self._socket_connect_ex = socket.socket.connect_ex
        self._create_connection = socket.create_connection
        self._getaddrinfo = socket.getaddrinfo
        self._active = False

    def __enter__(self) -> "OfflineGuard":
        if self._active:
            return self

        def deny_connect(sock: socket.socket, address: Any) -> None:
            raise NetworkAccessBlocked(f"network access blocked: {address!r}")

        def deny_connect_ex(sock: socket.socket, address: Any) -> int:
            raise NetworkAccessBlocked(f"network access blocked: {address!r}")

        def deny_create_connection(*args: Any, **kwargs: Any) -> socket.socket:
            address = args[0] if args else kwargs.get("address")
            raise NetworkAccessBlocked(f"network access blocked: {address!r}")

        def deny_getaddrinfo(*args: Any, **kwargs: Any) -> list:
            raise NetworkAccessBlocked(f"DNS access blocked: {args!r}")

        socket.socket.connect = deny_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = deny_connect_ex  # type: ignore[method-assign]
        socket.create_connection = deny_create_connection
        socket.getaddrinfo = deny_getaddrinfo
        self._active = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._active:
            return
        socket.socket.connect = self._socket_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = self._socket_connect_ex  # type: ignore[method-assign]
        socket.create_connection = self._create_connection
        socket.getaddrinfo = self._getaddrinfo
        self._active = False


def install_network_guard() -> OfflineGuard:
    guard = OfflineGuard()
    guard.__enter__()
    return guard


def assert_network_blocked() -> None:
    try:
        socket.create_connection(("example.com", 443), timeout=0.1)
    except NetworkAccessBlocked:
        return
    raise RuntimeError("offline guard did not block an outbound connection")

