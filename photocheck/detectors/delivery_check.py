"""Audit whether an A delivery is complete enough for runtime integration."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .a_adapter import AAdapterError, load_a_envelope

REQUIRED_ENGINE_FILES = (
    "__init__.py",
    "config.py",
    "entities.py",
    "face.py",
    "ocr.py",
    "pipeline.py",
    "qr.py",
    "qr_classify.py",
    "secret_store.py",
    "standin_loader.py",
)


@dataclass(frozen=True)
class ADeliveryReport:
    root: Path
    contract_sample_valid: bool
    contract_error: str | None
    detected_engine_files: tuple[str, ...]
    missing_engine_files: tuple[str, ...]
    missing_functions: tuple[str, ...]
    sample_images: tuple[str, ...]

    @property
    def detector_source_ready(self) -> bool:
        return (
            not self.missing_engine_files
            and not self.missing_functions
            and bool(self.sample_images)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "contract_sample_valid": self.contract_sample_valid,
            "contract_error": self.contract_error,
            "detected_engine_files": list(self.detected_engine_files),
            "missing_engine_files": list(self.missing_engine_files),
            "missing_functions": list(self.missing_functions),
            "sample_images": list(self.sample_images),
            "detector_source_ready": self.detector_source_ready,
        }


def inspect_a_delivery(root: str | Path) -> ADeliveryReport:
    delivery_root = Path(root).resolve(strict=True)
    if not delivery_root.is_dir():
        raise ValueError("A delivery root must be a directory")

    sample_path = delivery_root / "express_001.json"
    contract_valid = False
    contract_error: str | None = None
    if not sample_path.is_file():
        contract_error = "express_001.json is missing"
    else:
        try:
            load_a_envelope(sample_path)
            contract_valid = True
        except AAdapterError as exc:
            contract_error = str(exc)

    files_by_name: dict[str, list[Path]] = {}
    for path in delivery_root.rglob("*.py"):
        files_by_name.setdefault(path.name, []).append(path)
    found: list[str] = []
    missing: list[str] = []
    for name in REQUIRED_ENGINE_FILES:
        matches = files_by_name.get(name, [])
        if name == "__init__.py":
            matches = [path for path in matches if path.parent.name == "detect"]
        else:
            matches = [
                path
                for path in matches
                if path.parent.name == "detect" and path.parent.parent.name == "core"
            ]
        if matches:
            found.append(name)
        else:
            missing.append(name)

    missing_functions: list[str] = []
    function_expectations = {
        "pipeline.py": {"analyze", "probe_region"},
        "qr_classify.py": {"classify"},
    }
    for name, expected in function_expectations.items():
        candidates = [
            path
            for path in files_by_name.get(name, [])
            if path.parent.name == "detect" and path.parent.parent.name == "core"
        ]
        definitions: set[str] = set()
        for path in candidates:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, SyntaxError):
                continue
            definitions.update(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
        missing_functions.extend(
            f"{name}:{function}"
            for function in sorted(expected - definitions)
        )

    sample_images = tuple(
        str(path.relative_to(delivery_root))
        for path in sorted(delivery_root.rglob("express_001.*"))
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    return ADeliveryReport(
        root=delivery_root,
        contract_sample_valid=contract_valid,
        contract_error=contract_error,
        detected_engine_files=tuple(found),
        missing_engine_files=tuple(missing),
        missing_functions=tuple(missing_functions),
        sample_images=sample_images,
    )

