"""Typed records used by the GeoParquet publication boundary."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DATASET_SCHEMA_VERSION = "1.0.0"
CELL_SCHEMA_VERSION = "1.0.0"
FACT_SCHEMA_VERSION = "1.0.0"
GEOPARQUET_VERSION = "1.1.0"


@dataclass(frozen=True)
class PublishedPart:
    """Immutable reference and integrity evidence for one Parquet part."""

    table_name: str
    path: Path
    row_count: int
    checksum: str
    schema_version: str
    extent: tuple[float, float, float, float] | None = None
    origin_ids: tuple[str, ...] = ()

    def to_dict(self, root: Path | None = None) -> dict[str, Any]:
        """Serialize a part reference, relative to root when supplied."""
        location = self.path.relative_to(root).as_posix() if root else str(self.path)
        return {
            "table_name": self.table_name,
            "location": location,
            "row_count": self.row_count,
            "checksum": self.checksum,
            "checksum_algorithm": "sha256",
            "schema_version": self.schema_version,
            "extent": list(self.extent) if self.extent else None,
            "origin_ids": list(self.origin_ids),
        }


@dataclass(frozen=True)
class PartitionManifest:
    """Reconciliable collection of immutable parts for one logical table."""

    table_name: str
    partition_keys: tuple[str, ...]
    parts: tuple[PublishedPart, ...]
    row_count: int
    schema_version: str
    extent: tuple[float, float, float, float] | None = None

    def to_dict(self, root: Path | None = None) -> dict[str, Any]:
        """Return JSON-compatible partition metadata."""
        return {
            "table_name": self.table_name,
            "partition_keys": list(self.partition_keys),
            "parts": [part.to_dict(root) for part in self.parts],
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "extent": list(self.extent) if self.extent else None,
        }


@dataclass(frozen=True)
class DatasetManifest:
    """Immutable dataset-version metadata and reconciliation totals."""

    version_id: str
    status: str
    dataset_fingerprint: str
    result_compatibility_fingerprint: str
    eligibility_fingerprint: str
    candidate_provenance: dict[str, Any]
    solve_provenance: dict[str, Any]
    expected_key_count: int
    published_key_count: int
    dimension_row_count: int
    outcome_counts: dict[str, int]
    prefilter_pruned_count: int
    partition_manifests: tuple[PartitionManifest, ...]
    created_at: str
    schema_versions: dict[str, str] = field(default_factory=dict)
    geoparquet_version: str = GEOPARQUET_VERSION
    crs: str = "EPSG:4326"
    partition_scheme: str = "origin_h3_id_hex"
    spatial_ordering_policy: str = "canonical_h3_id"

    def to_dict(self, root: Path | None = None) -> dict[str, Any]:
        """Return stable, JSON-compatible dataset metadata."""
        return {
            "version_id": self.version_id,
            "status": self.status,
            "dataset_fingerprint": self.dataset_fingerprint,
            "result_compatibility_fingerprint": self.result_compatibility_fingerprint,
            "eligibility_fingerprint": self.eligibility_fingerprint,
            "candidate_provenance": self.candidate_provenance,
            "solve_provenance": self.solve_provenance,
            "expected_key_count": self.expected_key_count,
            "published_key_count": self.published_key_count,
            "dimension_row_count": self.dimension_row_count,
            "outcome_counts": self.outcome_counts,
            "prefilter_pruned_count": self.prefilter_pruned_count,
            "partition_manifests": [
                partition.to_dict(root) for partition in self.partition_manifests
            ],
            "created_at": self.created_at,
            "schema_versions": self.schema_versions,
            "geoparquet_version": self.geoparquet_version,
            "crs": self.crs,
            "partition_scheme": self.partition_scheme,
            "spatial_ordering_policy": self.spatial_ordering_policy,
        }


@dataclass(frozen=True)
class ValidationReport:
    """Result of validating staged publication tables and expected keys."""

    valid: bool
    errors: tuple[str, ...]
    outcome_counts: dict[str, int]


@dataclass(frozen=True)
class PublicationResult:
    """Version location and manifest returned after successful publication."""

    version_id: str
    version_path: Path
    manifest_path: Path
    success_path: Path
    current_reference: Path
    manifest: DatasetManifest


@dataclass(frozen=True)
class LoadedPublication:
    """Validated current version and its two logical Arrow tables."""

    version_id: str
    version_path: Path
    manifest: dict[str, Any]
    dimension: Any
    facts: Any
