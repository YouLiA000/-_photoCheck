"""Image ingestion and metadata detection."""

from .export import (
    ExportError,
    SanitizedExport,
    UnsafeExportError,
    sanitize_image,
    sanitize_ingested,
)
from .ingest import ImageIngestError, IngestedImage, ingest_image
from .metadata import MetadataScanError, metadata_residual_tags, read_metadata
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
from .verification import VerificationError, verify_redacted_export

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
    "apply_redactions",
    "expand_bbox",
    "ingest_image",
    "metadata_residual_tags",
    "process_and_export",
    "read_metadata",
    "redact_ingested",
    "sanitize_image",
    "sanitize_ingested",
    "verify_redacted_export",
]

