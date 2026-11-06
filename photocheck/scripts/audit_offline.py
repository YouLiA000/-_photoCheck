"""Static and runtime checks for PhotoCheck's offline operation claim."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BLOCKED_IMPORTS = {
    "aiohttp",
    "http.client",
    "httpx",
    "requests",
    "socket",
    "urllib.request",
}
BLOCKED_CALLS = {
    "create_connection",
    "request",
    "socket",
    "urlopen",
}
IGNORED_FILES = {
    "network_guard.py",
    "tests/test_offline_guard.py",
}


def scan_source(root: Path) -> dict[str, list[str]]:
    imports: list[str] = []
    calls: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative in IGNORED_FILES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as exc:
            imports.append(f"{relative}: unreadable source: {type(exc).__name__}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
                for module in modules:
                    if any(module == name or module.startswith(name + ".") for name in BLOCKED_IMPORTS):
                        imports.append(f"{relative}:{node.lineno}: import {module}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                if any(module == name or module.startswith(name + ".") for name in BLOCKED_IMPORTS):
                    imports.append(f"{relative}:{node.lineno}: from {module} import ...")
            elif isinstance(node, ast.Call):
                function = node.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else None
                )
                if name in BLOCKED_CALLS:
                    calls.append(f"{relative}:{node.lineno}: call {name}()")
    return {"imports": imports, "calls": calls}


def run_offline_smoke() -> dict[str, Any]:
    script = PROJECT_ROOT / "photocheck" / "scripts" / "run_end_to_end.py"
    sample = PROJECT_ROOT / "photocheck" / "detectors" / "a_engine" / "express_001.png"
    with tempfile.TemporaryDirectory() as temp_dir:
        report = Path(temp_dir) / "report.json"
        environment = os.environ.copy()
        environment["PHOTOCHECK_OFFLINE_GUARD"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                str(sample),
                "--output-dir",
                str(Path(temp_dir) / "output"),
                "--report",
                str(report),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            return {
                "ok": False,
                "returncode": completed.returncode,
                "stderr_tail": completed.stderr[-2000:],
            }
        payload = json.loads(report.read_text(encoding="utf-8"))
        return {
            "ok": payload.get("verification", {}).get("disposal_state") == "passed",
            "disposal_state": payload.get("verification", {}).get("disposal_state"),
            "detection_count": payload.get("detection_count"),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-smoke", action="store_true")
    args = parser.parse_args()

    static = scan_source(PROJECT_ROOT / "photocheck")
    result: dict[str, Any] = {
        "static": static,
        "static_ok": not static["imports"] and not static["calls"],
    }
    if args.run_smoke:
        result["runtime"] = run_offline_smoke()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["static_ok"]:
        return 1
    if args.run_smoke and not result["runtime"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
