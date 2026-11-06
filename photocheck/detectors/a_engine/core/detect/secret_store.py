"""Compatibility shim: B's delivery checker looks for `core/detect/secret_store.py`.

The implementation is NOT here, it stays in `core/secret_store.py`. Plaintext is
allowed to live in exactly one in-process container; a second copy would be a
second path to disk.
"""

from __future__ import annotations

from ..secret_store import SecretStore  # noqa: F401

__all__ = ["SecretStore"]
