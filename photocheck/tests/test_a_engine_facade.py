from __future__ import annotations

import unittest

from photocheck.detectors import a_detector_status
from photocheck.detectors import a_contract
from photocheck.detectors.a_engine import analyze, probe_region


class AEngineFacadeTests(unittest.TestCase):
    def test_engine_entry_points_are_exported(self) -> None:
        self.assertTrue(callable(analyze))
        self.assertTrue(callable(probe_region))

    def test_contract_facade_uses_engine_contract(self) -> None:
        from photocheck.detectors.a_engine.core import contract

        self.assertIs(a_contract.Detection, contract.Detection)
        self.assertIs(a_contract.ImageDescriptor, contract.ImageDescriptor)

    def test_detector_status_is_available(self) -> None:
        status = a_detector_status()
        self.assertIn("ocr", status)
        self.assertIn("qr", status)
        self.assertIn("face", status)
        self.assertIn("qr_backend", status)


if __name__ == "__main__":
    unittest.main()
