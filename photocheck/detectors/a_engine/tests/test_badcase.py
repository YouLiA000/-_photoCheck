"""Tests for the archive rules themselves.

If the rules do not actually bite, the case library decays into a bug graveyard
within three months. Every assertion here maps to one rule from the spec card.

Note: the `## 复现` / `## 处置` headings are Chinese on purpose - they match the
template used by the archived Markdown documents under badcases/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from photocheck.detectors.a_engine.core.badcase import BadcaseError, build_index, load_all, parse_front_matter

ROOT = Path(__file__).resolve().parent.parent

VALID = """---
id: BC-9001
title: sample
found_at: 2026-11-02
layer: detection
reason: rule_miss
symptom: false_negative
kind: text
subtype: phone
card: K-04
severity: P1
status: {status}
spec_ref: spec card §K-04
{extra}---
## 现象
sample

## 复现
```bash
echo hi
```

{tail}
"""


def _write(
    root: Path,
    *,
    subtype="phone",
    reason="rule_miss",
    status="fixed",
    extra="fix_test: test_demo\n",
    tail="## 修复\nfixed.",
):
    d = root / "badcases" / f"{subtype}__{reason}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "BC-9001-demo.md").write_text(
        VALID.format(status=status, extra=extra, tail=tail), encoding="utf-8"
    )


def _tests_dir(root: Path, names=("test_demo",)):
    d = root / "tests"
    d.mkdir(parents=True, exist_ok=True)
    (d / "test_demo_mod.py").write_text(
        "\n".join(f"def {n}():\n    assert True\n" for n in names), encoding="utf-8"
    )


def test_shipped_library_is_valid():
    """Every case that ships in the repo must pass validation."""
    cases = load_all(ROOT / "badcases", tests_dir=ROOT / "tests")
    assert cases, "the case library is empty"
    assert all(
        c.meta["reason"] in {"ocr_miss", "ocr_error", "rule_miss", "threshold", "overlap"}
        for c in cases
    )


def test_index_counts_match(tmp_path):
    _tests_dir(tmp_path)
    _write(tmp_path)
    index = build_index(load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests"))
    assert index["total"] == 1
    # Labels in the index are the Chinese ones fixed by spec card R-02.
    assert index["by_reason"] == {"规则未匹配": 1}
    assert index["by_status"] == {"fixed": 1}


def test_fixed_without_fix_test_is_rejected(tmp_path):
    _tests_dir(tmp_path)
    _write(tmp_path, extra="")
    with pytest.raises(BadcaseError, match="fix_test"):
        load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")


def test_fix_test_must_exist_in_tests(tmp_path):
    _tests_dir(tmp_path, names=("test_something_else",))
    _write(tmp_path)
    with pytest.raises(BadcaseError, match="no matching test function"):
        load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")


@pytest.mark.parametrize(
    "kwargs,match",
    [
        (dict(reason="mystery"), "reason"),
        (dict(subtype="phone", reason="rule_miss"), None),  # directory agrees, must pass
    ],
)
def test_reason_must_be_one_of_five(tmp_path, kwargs, match):
    _tests_dir(tmp_path)
    _write(tmp_path, **kwargs)
    if match is None:
        load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")
    else:
        with pytest.raises(BadcaseError, match=match):
            load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")


def test_directory_must_match_subtype_and_reason(tmp_path):
    """Front matter says phone/rule_miss but the file sits in idcard__rule_miss/."""
    _tests_dir(tmp_path)
    d = tmp_path / "badcases" / "idcard__rule_miss"
    d.mkdir(parents=True)
    (d / "BC-9001-demo.md").write_text(
        VALID.format(status="fixed", extra="fix_test: test_demo\n", tail="## 修复\nfixed."),
        encoding="utf-8",
    )
    with pytest.raises(BadcaseError, match="directory must be"):
        load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")


def test_missing_reproduce_section_is_rejected(tmp_path):
    _tests_dir(tmp_path)
    _write(tmp_path, tail="## 修复\nfixed.")
    path = next((tmp_path / "badcases").glob("*/*.md"))
    path.write_text(
        path.read_text(encoding="utf-8").replace("## 复现", "## 现象2"), encoding="utf-8"
    )
    with pytest.raises(BadcaseError, match="reproduce"):
        load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")


def test_open_case_must_explain_disposal(tmp_path):
    _tests_dir(tmp_path)
    _write(tmp_path, status="open", extra="", tail="## 修复\nnot fixed yet.")
    with pytest.raises(BadcaseError, match="disposition"):
        load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")


def test_open_case_with_disposal_passes(tmp_path):
    _tests_dir(tmp_path)
    _write(tmp_path, status="open", extra="", tail="## 处置\nwaiting for the dataset.")
    cases = load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")
    assert cases[0].status == "open"


def test_duplicate_id_is_rejected(tmp_path):
    _tests_dir(tmp_path)
    _write(tmp_path)
    src = next((tmp_path / "badcases").glob("*/*.md"))
    dup = src.parent / "BC-9001-another.md"
    dup.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(BadcaseError, match="duplicate id"):
        load_all(tmp_path / "badcases", tests_dir=tmp_path / "tests")


def test_front_matter_parser_requires_fence():
    with pytest.raises(BadcaseError, match="front matter"):
        parse_front_matter("# no header\nbody")
