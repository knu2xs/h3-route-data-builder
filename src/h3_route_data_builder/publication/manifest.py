"""Deterministic construction and validation of publication manifests."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from h3_route_data_builder.publication.models import (
    CELL_SCHEMA_VERSION,
    DATASET_SCHEMA_VERSION,
    FACT_SCHEMA_VERSION,
    GEOPARQUET_VERSION,
    DatasetManifest,
    PartitionManifest,
    PublishedPart,
)


def build_partition_manifest(
    table_name: str, parts: list[PublishedPart] | tuple[PublishedPart, ...]
) -> PartitionManifest:
    """Build partition totals and extents from their immutable part references."""
    if table_name not in {"solvable_cells", "od_facts"}:
        raise ValueError(f"Unknown publication table: {table_name}")
    if any(part.table_name != table_name for part in parts):
        raise ValueError("Partition contains a part for a different table")
    row_count = sum(part.row_count for part in parts)
    extents = [part.extent for part in parts if part.extent is not None]
    extent = (
        (
            min(value[0] for value in extents),
            min(value[1] for value in extents),
            max(value[2] for value in extents),
            max(value[3] for value in extents),
        )
        if extents
        else None
    )
    schema_version = CELL_SCHEMA_VERSION if table_name == "solvable_cells" else FACT_SCHEMA_VERSION
    partition_keys = ("h3_id",) if table_name == "solvable_cells" else ("origin_h3_id",)
    return PartitionManifest(
        table_name=table_name,
        partition_keys=partition_keys,
        parts=tuple(parts),
        row_count=row_count,
        schema_version=schema_version,
        extent=extent,
    )


def build_dataset_manifest(
    version_id: str,
    dataset_fingerprint: str,
    result_compatibility_fingerprint: str,
    eligibility_fingerprint: str,
    candidate_provenance: dict[str, Any],
    solve_provenance: dict[str, Any],
    expected_key_count: int,
    published_key_count: int,
    dimension_row_count: int,
    outcome_counts: dict[str, int],
    prefilter_pruned_count: int,
    partition_manifests: list[PartitionManifest] | tuple[PartitionManifest, ...],
    created_at: str | None = None,
) -> DatasetManifest:
    """Construct a complete-status manifest after the caller validates all data."""
    required = (
        version_id,
        dataset_fingerprint,
        result_compatibility_fingerprint,
        eligibility_fingerprint,
    )
    if any(not value.strip() for value in required):
        raise ValueError("Version and fingerprint identities must be non-empty")
    if (
        min(
            expected_key_count,
            published_key_count,
            dimension_row_count,
            prefilter_pruned_count,
        )
        < 0
    ):
        raise ValueError("Manifest counts must be non-negative")
    if any(count < 0 for count in outcome_counts.values()):
        raise ValueError("Outcome counts must be non-negative")
    names = [partition.table_name for partition in partition_manifests]
    if sorted(names) != ["od_facts", "solvable_cells"]:
        raise ValueError("Manifest must reference both logical publication tables exactly once")
    return DatasetManifest(
        version_id=version_id,
        status="complete",
        dataset_fingerprint=dataset_fingerprint,
        result_compatibility_fingerprint=result_compatibility_fingerprint,
        eligibility_fingerprint=eligibility_fingerprint,
        candidate_provenance=candidate_provenance,
        solve_provenance=solve_provenance,
        expected_key_count=expected_key_count,
        published_key_count=published_key_count,
        dimension_row_count=dimension_row_count,
        outcome_counts=outcome_counts,
        prefilter_pruned_count=prefilter_pruned_count,
        partition_manifests=tuple(partition_manifests),
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        schema_versions={
            "dataset": DATASET_SCHEMA_VERSION,
            "solvable_cells": CELL_SCHEMA_VERSION,
            "od_facts": FACT_SCHEMA_VERSION,
        },
        geoparquet_version=GEOPARQUET_VERSION,
    )


def validate_manifest(document: dict[str, Any], root: Path) -> list[str]:
    """Validate manifest structure, references, and reconciled part totals."""
    errors: list[str] = []
    versions = {
        "dataset": DATASET_SCHEMA_VERSION,
        "solvable_cells": CELL_SCHEMA_VERSION,
        "od_facts": FACT_SCHEMA_VERSION,
    }
    if document.get("schema_versions") != versions:
        errors.append("Dataset manifest has incompatible integer schema versions")
    if document.get("status") != "complete":
        errors.append("Dataset manifest is not complete")
    if document.get("geoparquet_version") != GEOPARQUET_VERSION:
        errors.append("Dataset manifest has an incompatible GeoParquet version")
    if not document.get("dataset_fingerprint") or not document.get(
        "result_compatibility_fingerprint"
    ):
        errors.append("Dataset manifest is missing compatibility fingerprints")
    table_names: set[str] = set()
    for partition in document.get("partition_manifests", []):
        table_name = partition.get("table_name")
        expected_version = versions.get(table_name)
        if expected_version is None or partition.get("schema_version") != expected_version:
            errors.append(f"Incompatible partition schema version for {table_name}")
        if table_name in table_names:
            errors.append(f"Duplicate partition manifest for {table_name}")
        table_names.add(table_name)
        parts = partition.get("parts", [])
        count = 0
        for part in parts:
            if part.get("schema_version") != expected_version:
                errors.append(f"Incompatible part schema version for {table_name}")
            location = part.get("location")
            if not location:
                errors.append(f"{table_name} part has no location")
                continue
            path = root / Path(location)
            count += int(part.get("row_count", -1))
            if not path.is_file():
                errors.append(f"Manifest part is missing: {location}")
            elif not path.resolve().is_relative_to(root.resolve()):
                errors.append(f"Manifest part escapes the version directory: {location}")
        if count != partition.get("row_count"):
            errors.append(f"{table_name} manifest row totals do not reconcile")
    if table_names != {"solvable_cells", "od_facts"}:
        errors.append("Dataset manifest must reference solvable_cells and od_facts")
    if sum(
        int(partition.get("row_count", -1))
        for partition in document.get("partition_manifests", [])
        if partition.get("table_name") == "od_facts"
    ) != document.get("published_key_count"):
        errors.append("OD partition totals do not equal published_key_count")
    dimension_rows = sum(
        int(partition.get("row_count", -1))
        for partition in document.get("partition_manifests", [])
        if partition.get("table_name") == "solvable_cells"
    )
    if dimension_rows != document.get("dimension_row_count"):
        errors.append("Cell partition totals do not equal dimension_row_count")
    outcome_counts = document.get("outcome_counts", {})
    if sum(outcome_counts.values()) != document.get("expected_key_count"):
        errors.append("Outcome totals do not equal expected_key_count")
    if outcome_counts.get("qualifying", 0) + outcome_counts.get("self_pair", 0) != (
        document.get("published_key_count")
    ):
        errors.append("Qualifying and self-pair outcomes do not equal published_key_count")
    return errors
