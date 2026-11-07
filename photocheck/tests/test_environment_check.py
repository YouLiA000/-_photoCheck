from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "check_environment.py"
)
spec = importlib.util.spec_from_file_location("photocheck_check_environment", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class EnvironmentCheckTests(unittest.TestCase):
    def test_face_unavailable_is_warning_not_failure(self) -> None:
        problems, warnings = module.assess_detector_status(
            {"ocr": "ok", "qr": "ok", "face": "unavailable"}
        )
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 1)

    def test_ocr_or_qr_unavailable_is_failure(self) -> None:
        problems, _ = module.assess_detector_status(
            {"ocr": "unavailable", "qr": "unavailable", "face": "ok"}
        )
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
