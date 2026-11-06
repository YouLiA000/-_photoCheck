"""Parsing and hard validation for the failure-case library (R-02 / deliverable 3).

Each badcase is a Markdown file that starts with a `---` fenced front matter block.
This module reads the directory into structured records and turns the archiving
rules into checks that raise, instead of relying on discipline:

1. The directory name must be `<subtype>__<reason>` and must agree with the front matter.
2. `reason` may only use the 5 failure causes from the spec card; same for
   `layer` / `status` / `severity`.
3. `id` is globally unique and must be the file name prefix.
4. `status: fixed` requires `fix_test`, and that test function must actually exist
   under tests/. This is the only mechanism that stops the same pit from being
   stepped into twice.
5. `status: open` / `wontfix` must state the disposition in the body; no silent
   hanging entries.

Encoding note: all code, comments and messages are English so that the file can
be read and printed under any Windows code page. The only non-ASCII literals left
are data-facing: (a) the spec-mandated reason labels that end up in
`badcases/index.json`, and (b) the Chinese section headings used by the archived
Markdown documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "REASONS",
    "LAYERS",
    "SYMPTOMS",
    "SEVERITIES",
    "STATUSES",
    "Badcase",
    "BadcaseError",
    "load_all",
    "build_index",
    "parse_front_matter",
]

# Spec card R-02 fixes these 5 failure causes; do not add or remove entries.
# Values are the Chinese labels required by the deliverable, not UI strings.
REASONS: dict[str, str] = {
    "ocr_miss": "OCR 未检出",
    "ocr_error": "OCR 错字",
    "rule_miss": "规则未匹配",
    "threshold": "阈值误判",
    "overlap": "多目标重叠",
}

LAYERS: dict[str, str] = {
    "detection": "检测逻辑",
    "contract": "记录结构与校验",
    "env": "依赖 / 路径 / 模型文件",
}

SYMPTOMS = ("false_negative", "false_positive", "wrong_subtype", "silent_drop", "crash")
SEVERITIES = ("P0", "P1", "P2")
STATUSES = ("open", "fixed", "wontfix")

REQUIRED_FIELDS = (
    "id",
    "title",
    "found_at",
    "layer",
    "reason",
    "symptom",
    "kind",
    "subtype",
    "card",
    "severity",
    "status",
    "spec_ref",
)

_ID_PATTERN = re.compile(r"^BC-\d{4}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TEST_DEF = re.compile(r"^def (test_\w+)\(", re.MULTILINE)

# Matches the archived Markdown headings. Data-facing: the case files are written
# in Chinese, so these literals stay Chinese by design.
_DISPOSITION_HEADING = re.compile(r"^## (处置|未修)", re.MULTILINE)
_REPRODUCE_HEADING = "## 复现"


class BadcaseError(ValueError):
    """The archive does not follow the required rules."""


@dataclass(frozen=True)
class Badcase:
    meta: Mapping[str, str]
    body: str
    path: Path

    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def reason(self) -> str:
        return self.meta["reason"]

    @property
    def status(self) -> str:
        return self.meta["status"]

    @property
    def directory(self) -> str:
        return self.path.parent.name

    def to_dict(self) -> dict[str, Any]:
        return {
            **dict(self.meta),
            "reason_label": REASONS.get(self.meta["reason"], ""),
            "path": self.path.as_posix(),
            "directory": self.directory,
        }


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Parse the `---` fenced key: value header.

    No PyYAML on purpose: a flat string map is all this needs, and a dependency
    here would only add an install failure mode on the target machine.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise BadcaseError("missing front matter: the file must start with ---")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise BadcaseError("front matter is not closed with ---") from exc

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise BadcaseError(f"cannot parse front matter line: {line!r}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, "\n".join(lines[end + 1 :]).lstrip("\n")


def _known_tests(tests_dir: Path) -> set[str]:
    names: set[str] = set()
    if not tests_dir.is_dir():
        return names
    for path in tests_dir.glob("test_*.py"):
        names.update(_TEST_DEF.findall(path.read_text(encoding="utf-8")))
    return names


def _check_one(case: Badcase, known_tests: set[str]) -> list[str]:
    meta = case.meta
    where = f"{case.path.as_posix()}"
    problems: list[str] = []

    missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        problems.append(f"{where}: missing required fields {missing}")
        return problems  # every later check depends on these fields

    if not _ID_PATTERN.fullmatch(meta["id"]):
        problems.append(f"{where}: id must look like BC-0001, got {meta['id']!r}")
    if not case.path.name.startswith(meta["id"]):
        problems.append(f"{where}: file name must start with the id ({meta['id']})")
    if not _DATE_PATTERN.fullmatch(meta["found_at"]):
        problems.append(f"{where}: found_at must be YYYY-MM-DD, got {meta['found_at']!r}")

    if meta["reason"] not in REASONS:
        problems.append(f"{where}: reason must be one of {sorted(REASONS)}, got {meta['reason']!r}")
    if meta["layer"] not in LAYERS:
        problems.append(f"{where}: layer must be one of {sorted(LAYERS)}, got {meta['layer']!r}")
    if meta["symptom"] not in SYMPTOMS:
        problems.append(f"{where}: symptom must be one of {list(SYMPTOMS)}, got {meta['symptom']!r}")
    if meta["severity"] not in SEVERITIES:
        problems.append(f"{where}: severity must be one of {list(SEVERITIES)}, got {meta['severity']!r}")
    if meta["status"] not in STATUSES:
        problems.append(f"{where}: status must be one of {list(STATUSES)}, got {meta['status']!r}")

    expected_dir = f"{meta['subtype']}__{meta['reason']}"
    if case.directory != expected_dir:
        problems.append(
            f"{where}: directory must be {expected_dir}/ (subtype__reason), actual {case.directory}/"
        )

    if meta["status"] == "fixed":
        fix_test = meta.get("fix_test", "")
        if not fix_test:
            problems.append(
                f"{where}: status=fixed but no fix_test given - a fixed issue needs a regression test"
            )
        elif fix_test not in known_tests:
            problems.append(f"{where}: fix_test={fix_test!r} has no matching test function under tests/")
    elif not _DISPOSITION_HEADING.search(case.body):
        problems.append(
            f"{where}: status={meta['status']} must state a disposition under a "
            f"'## 处置' or '## 未修' heading"
        )

    if _REPRODUCE_HEADING not in case.body:
        problems.append(
            f"{where}: missing '## 复现' section - a case nobody can reproduce is not archived"
        )

    return problems


def load_all(root: Path | str, *, tests_dir: Path | str | None = None) -> list[Badcase]:
    """Load and validate every badcase; raise once with all problems, not one by one."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise BadcaseError(f"directory does not exist: {root_path}")
    tests_path = Path(tests_dir) if tests_dir is not None else root_path.parent / "tests"
    known = _known_tests(tests_path)

    cases: list[Badcase] = []
    for path in sorted(root_path.glob("*/*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        cases.append(Badcase(meta=meta, body=body, path=path))

    problems: list[str] = []
    for case in cases:
        problems.extend(_check_one(case, known))

    seen: dict[str, Path] = {}
    for case in cases:
        cid = case.meta.get("id", "")
        if cid in seen:
            problems.append(f"duplicate id: {cid} ({seen[cid]} and {case.path})")
        else:
            seen[cid] = case.path

    if problems:
        raise BadcaseError(
            "failure-case library violates the archive rules:\n  - " + "\n  - ".join(problems)
        )
    return cases


def build_index(cases: Iterable[Badcase]) -> dict[str, Any]:
    """Build the machine-readable index.

    It feeds the eval report and the closing materials; it never replaces the .md
    sources.
    """
    items = [case.to_dict() for case in sorted(cases, key=lambda c: c.id)]
    by_reason: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for item in items:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {
        "total": len(items),
        "by_reason": {REASONS[k]: v for k, v in by_reason.items()},
        "by_status": by_status,
        "items": items,
    }
