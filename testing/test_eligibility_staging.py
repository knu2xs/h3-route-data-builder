"""Tests for atomic eligibility-part staging."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from h3_route_data_builder.eligibility.models import (
    CellGeometryCandidate,
    EdgeIntersectionEvidence,
)
from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    EligibilityStatus,
    NetworkLocation,
    PartitionStatus,
    RunStatus,
)
from h3_route_data_builder.eligibility.reconcile import (
    finalize_eligibility_results,
    reconcile_cell_candidates,
)
from h3_route_data_builder.eligibility.run_state import (
    create_run_state,
    transition_partition,
)
from h3_route_data_builder.eligibility.staging import (
    read_verified_staged_part,
    stage_table_batches,
    write_staged_part,
)


def make_geoparquet_table(row_count: int) -> pa.Table:
    """Create a small WKB table with GeoParquet metadata for staging tests."""
    metadata = {
        b"geo": json.dumps(
            {
                "version": "1.0.0",
                "primary_column": "geometry",
                "columns": {
                    "geometry": {
                        "encoding": "WKB",
                        "geometry_types": ["Point"],
                        "crs": None,
                    }
                },
            }
        ).encode("utf-8")
    }
    schema = pa.schema(
        [pa.field("h3_id_hex", pa.string()), pa.field("geometry", pa.binary())],
        metadata=metadata,
    )
    return pa.Table.from_arrays(
        [
            pa.array([f"cell-{index}" for index in range(row_count)]),
            pa.array([b"wkb"] * row_count),
        ],
        schema=schema,
    )


def test_staged_part_is_atomic_and_returns_checksum(temp_dir) -> None:
    output_path = temp_dir / "parts" / "part-a.parquet"
    table = make_geoparquet_table(2)

    staged = write_staged_part(table, output_path, "part-a", row_limit=2)

    assert staged.path == output_path
    assert staged.row_count == 2
    assert len(staged.checksum) == 64
    assert pq.read_table(output_path).num_rows == 2
    assert not list(output_path.parent.glob("*.tmp"))


def test_staging_rejects_part_over_row_limit(temp_dir) -> None:
    with pytest.raises(ValueError, match="configured limit"):
        write_staged_part(
            make_geoparquet_table(2), temp_dir / "part.parquet", "part", 1
        )


def test_staging_requires_geoparquet_metadata(temp_dir) -> None:
    table = pa.table({"h3_id_hex": ["cell"]})

    with pytest.raises(ValueError, match="GeoParquet schema metadata"):
        write_staged_part(table, temp_dir / "part.parquet", "part", 1)


def test_large_batch_is_split_deterministically_without_row_loss(temp_dir) -> None:
    table = make_geoparquet_table(5)

    first_run = stage_table_batches(
        table, temp_dir / "run-a", "batch", batch_size=5, part_row_limit=2
    )
    second_run = stage_table_batches(
        table, temp_dir / "run-b", "batch", batch_size=5, part_row_limit=2
    )

    assert [part.row_count for part in first_run] == [2, 2, 1]
    assert [part.part_key for part in first_run] == [
        part.part_key for part in second_run
    ]
    staged_ids = [
        cell_id
        for part in first_run
        for cell_id in read_verified_staged_part(part).column("h3_id_hex").to_pylist()
    ]
    assert staged_ids == [f"cell-{index}" for index in range(5)]


def test_staged_part_checksum_mismatch_is_rejected(temp_dir) -> None:
    staged = write_staged_part(
        make_geoparquet_table(1), temp_dir / "part.parquet", "part", 1
    )
    staged.path.write_bytes(b"corrupted")

    with pytest.raises(ValueError, match="checksum mismatch"):
        read_verified_staged_part(staged)


def test_reconciliation_deduplicates_h3_cells_and_edge_identities() -> None:
    first = CellGeometryCandidate(
        h3_id_hex="8928308280fffff",
        resolution=9,
        cell_geometry=None,
        centroid_geometry=None,
        intersecting_edges=(
            EdgeIntersectionEvidence(1, 10, None, None),
            EdgeIntersectionEvidence(1, 11, None, None),
        ),
        eligibility_reason="eligible edge intersects cell within AOI",
    )
    duplicate = CellGeometryCandidate(
        h3_id_hex="8928308280FFFFF",
        resolution=9,
        cell_geometry=None,
        centroid_geometry=None,
        intersecting_edges=(EdgeIntersectionEvidence(1, 10, None, None),),
        eligibility_reason="eligible edge intersects cell within AOI",
    )

    result = reconcile_cell_candidates(
        {"partition-b": [duplicate], "partition-a": [first]},
        expected_partition_keys=["partition-a", "partition-b"],
    )

    assert len(result) == 1
    assert result[0].h3_id_hex == "8928308280fffff"
    assert [
        (edge.source_id, edge.source_oid) for edge in result[0].intersecting_edges
    ] == [
        (1, 10),
        (1, 11),
    ]


def test_reconciliation_rejects_missing_expected_partition() -> None:
    with pytest.raises(ValueError, match="Missing expected partitions"):
        reconcile_cell_candidates(
            {"partition-a": []},
            expected_partition_keys=["partition-a", "partition-b"],
        )


def make_valid_cell_result(h3_id_hex: str) -> CellEligibilityResult:
    """Create one validated solvable result for finalization tests."""
    return CellEligibilityResult(
        h3_id_hex=h3_id_hex,
        resolution=9,
        eligibility_status=EligibilityStatus.SOLVABLE,
        eligibility_reason="eligible edge intersects cell within AOI",
        intersecting_edge_count=1,
        representative=NetworkLocation(
            x=1.0,
            y=1.0,
            source_id=1,
            source_oid=10,
            pos_along=0.5,
            side_of_edge=1,
            snap_distance_m=0.0,
        ),
    )


def mark_partition_reconciled(run_state, partition_key: str) -> None:
    """Move one partition into its final reconciled state."""
    for status in (
        PartitionStatus.PROCESSING,
        PartitionStatus.STAGED,
        PartitionStatus.RECONCILED,
    ):
        transition_partition(run_state, partition_key, status)


def test_handoff_counts_unique_validated_solvable_cells(temp_dir) -> None:
    run_state = create_run_state("run-1", ["partition-a"], total_output_hard_cap=2)
    mark_partition_reconciled(run_state, "partition-a")
    first = make_valid_cell_result("8928308280fffff")
    second = make_valid_cell_result("8928308280bffff")
    ineligible = CellEligibilityResult(
        h3_id_hex="8928308280affff",
        resolution=9,
        eligibility_status=EligibilityStatus.INELIGIBLE,
        eligibility_reason="no eligible edge",
        intersecting_edge_count=0,
    )

    handoff = finalize_eligibility_results(
        run_state,
        [first, ineligible, second],
        snap_tolerance_m=0.01,
    )

    assert handoff == [first, second]
    assert run_state.unique_solvable_cell_count == 2
    assert run_state.status == RunStatus.COMPLETE


def test_total_cap_overflow_fails_run_without_partial_handoff() -> None:
    run_state = create_run_state("run-1", ["partition-a"], total_output_hard_cap=1)
    mark_partition_reconciled(run_state, "partition-a")

    with pytest.raises(ValueError, match="total output hard cap"):
        finalize_eligibility_results(
            run_state,
            [
                make_valid_cell_result("8928308280fffff"),
                make_valid_cell_result("8928308280bffff"),
            ],
            snap_tolerance_m=0.01,
        )

    assert run_state.status == RunStatus.FAILED_INCOMPLETE


def test_unreconciled_partition_keeps_run_incomplete() -> None:
    run_state = create_run_state(
        "run-1", ["partition-a", "partition-b"], total_output_hard_cap=2
    )
    mark_partition_reconciled(run_state, "partition-a")

    with pytest.raises(ValueError, match="unreconciled partitions"):
        finalize_eligibility_results(
            run_state,
            [make_valid_cell_result("8928308280fffff")],
            snap_tolerance_m=0.01,
        )

    assert run_state.status == RunStatus.FAILED_INCOMPLETE
