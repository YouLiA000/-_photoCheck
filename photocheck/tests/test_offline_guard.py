from __future__ import annotations

import unittest

from photocheck.network_guard import NetworkAccessBlocked, OfflineGuard, assert_network_blocked


class OfflineGuardTests(unittest.TestCase):
    def test_guard_blocks_connections_and_restores_socket(self) -> None:
        import socket

        original = socket.create_connection
        with OfflineGuard():
            with self.assertRaises(NetworkAccessBlocked):
                socket.create_connection(("example.com", 443), timeout=0.1)
            with self.assertRaises(NetworkAccessBlocked):
                socket.getaddrinfo("example.com", 443)
        self.assertIs(socket.create_connection, original)

    def test_canary_proves_guard_is_active(self) -> None:
        with OfflineGuard():
            assert_network_blocked()


if __name__ == "__main__":
    unittest.main()
