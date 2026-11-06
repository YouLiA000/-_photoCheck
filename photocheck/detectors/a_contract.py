"""Backward-compatible import surface for the vendored A v4 contract.

The authoritative implementation now lives with the A engine so runtime output
and adapter validation cannot drift onto different versions of the contract.
"""

from .a_engine.core.contract import *
from .a_engine.core.contract import __all__
