from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "photocheck" / "interfaces.json"


class InterfaceManifestTests(unittest.TestCase):
    def test_manifest_entries_are_importable(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(payload["contract_version"], "photocheck/v4")
        for name, entry in payload["entries"].items():
            with self.subTest(entry=name):
                module = importlib.import_module(entry["module"])
                self.assertTrue(callable(getattr(module, entry["function"])))

    def test_declared_schema_exists(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertTrue((ROOT / payload["contract_schema"]).is_file())


if __name__ == "__main__":
    unittest.main()
