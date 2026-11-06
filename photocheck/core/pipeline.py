"""Pre-detector processing pipeline: redact, export and structurally verify."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from photocheck.contract import validate_records

from .export import SanitizedExport, sanitize_image
from .full_recheck import full_file_recheck
from .ingest import IngestedImage
from .redaction import redact_ingested
from .verification import ContentProbe, VerificationError, verify_redacted_export


@dataclass(frozen=True)
class ProcessingResult:
    export: SanitizedExport
    verification: dict[str, Any]
    full_recheck: dict[str, Any] | None = None


def process_and_export(
    ingested: IngestedImage,
    plan: Mapping[str, Any],
    *,
    output_dir: str | os.PathLike[str],
    detections: Iterable[Mapping[str, Any]] = (),
    decisions: Iterable[Mapping[str, Any]] = (),
    exiftool_path: str | os.PathLike[str] | None = None,
    content_probe: ContentProbe | None = None,
    run_full_recheck: bool = False,
) -> ProcessingResult:
    """Apply redactions, export a clean copy and produce a verification report."""

    detections = [dict(detection) for detection in detections]
    decisions = [dict(decision) for decision in decisions]
    try:
        validate_records([ingested.descriptor, *detections, *decisions, dict(plan)])
    except Exception as exc:
        raise VerificationError(f"invalid workflow records: {exc}") from exc
    with redact_ingested(ingested, plan, detections=detections) as redacted:
        exported = sanitize_image(
            redacted.image,
            output_dir,
            source_format=ingested.source_format,
            source_sha256=ingested.source_sha256,
            exiftool_path=exiftool_path,
        )
        try:
            report = verify_redacted_export(
                ingested,
                exported.output_path,
                plan,
                redacted,
                detections=detections,
                decisions=decisions,
                exiftool_path=exiftool_path,
                content_probe=content_probe,
            )
        except VerificationError:
            exported.output_path.unlink(missing_ok=True)
            raise
    recheck = (
        full_file_recheck(
            str(exported.output_path),
            plan,
            detections,
            decisions,
        )
        if run_full_recheck
        else None
    )
    return ProcessingResult(export=exported, verification=report, full_recheck=recheck)

