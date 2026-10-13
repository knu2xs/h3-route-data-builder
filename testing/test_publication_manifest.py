"""Manifest serialization and part-reference reconciliation tests."""

from h3_route_data_builder.publication.manifest import (
    build_dataset_manifest,
    build_partition_manifest,
)
from h3_route_data_builder.publication.models import PublishedPart


def test_manifest_records_versions_counts_provenance_and_part_integrity(
    temp_dir,
) -> None:
    cell_path = temp_dir / "solvable_cells.parquet"
    cell_path.write_bytes(b"test")
    part = PublishedPart(
        "solvable_cells",
        cell_path,
        row_count=3,
        checksum="a" * 64,
        schema_version="1.0.0",
        extent=(-123.0, 46.0, -121.0, 48.0),
    )
    partition = build_partition_manifest("solvable_cells", [part])
    empty_partition = build_partition_manifest("od_facts", [])
    manifest = build_dataset_manifest(
        version_id="version-1",
        dataset_fingerprint="dataset-1",
        result_compatibility_fingerprint="result-1",
        eligibility_fingerprint="eligibility-1",
        candidate_provenance={"mode": "aoi_only"},
        solve_provenance={"state": "complete"},
        expected_key_count=3,
        published_key_count=2,
        dimension_row_count=3,
        outcome_counts={"qualifying": 2, "unreachable": 1},
        prefilter_pruned_count=4,
        partition_manifests=[partition, empty_partition],
        created_at="2026-01-01T00:00:00Z",
    )

    document = manifest.to_dict(root=temp_dir)
    assert document["status"] == "complete"
    assert document["geoparquet_version"] == "1.1.0"
    assert document["schema_versions"] == {
        "dataset": "1.0.0",
        "solvable_cells": "1.0.0",
        "od_facts": "1.0.0",
    }
    assert document["partition_manifests"][0]["row_count"] == 3
    assert document["partition_manifests"][0]["parts"][0]["location"] == (
        "solvable_cells.parquet"
    )
    assert (
        document["partition_manifests"][0]["parts"][0]["checksum_algorithm"] == "sha256"
    )
