"""Image ingestion and metadata detection."""

from .export import (
    ExportError,
    SanitizedExport,
    UnsafeExportError,
    sanitize_image,
    sanitize_ingested,
)
from .full_recheck import full_file_recheck
from .ingest import ImageIngestError, IngestedImage, ingest_image
from .metadata import (
    MetadataScanError,
    exiftool_version,
    metadata_residual_tags,
    read_metadata,
)
from .pipeline import ProcessingResult, process_and_export
from .redaction import (
    AppliedRegion,
    RedactedImage,
    RedactionError,
    apply_redactions,
    expand_bbox,
    redact_ingested,
)
from .secrets import SecretStore
from .verification import ContentProbe, VerificationError, verify_redacted_export

__all__ = [
    "ImageIngestError",
    "IngestedImage",
    "MetadataScanError",
    "ExportError",
    "ProcessingResult",
    "RedactedImage",
    "RedactionError",
    "SanitizedExport",
    "SecretStore",
    "UnsafeExportError",
    "VerificationError",
    "AppliedRegion",
    "ContentProbe",
    "apply_redactions",
    "expand_bbox",
    "full_file_recheck",
    "ingest_image",
    "exiftool_version",
    "metadata_residual_tags",
    "process_and_export",
    "read_metadata",
    "redact_ingested",
    "sanitize_image",
    "sanitize_ingested",
    "verify_redacted_export",
]

