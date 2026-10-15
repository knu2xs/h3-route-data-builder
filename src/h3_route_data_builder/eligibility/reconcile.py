"""Deterministic reconciliation of H3 cell evidence across input partitions."""

from collections.abc import Iterable, Mapping

from h3_route_data_builder.utils import get_logger

from .cells import canonical_h3_ids
from .models import (
    CellEligibilityResult,
    CellGeometryCandidate,
    EdgeIntersectionEvidence,
    EligibilityRunState,
    RunStatus,
    validated_solvable_results,
)
from .run_state import finalize_run

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


def reconcile_cell_candidates(
    partition_candidates: Mapping[str, Iterable[CellGeometryCandidate]],
    expected_partition_keys: Iterable[str],
) -> list[CellGeometryCandidate]:
    """Deduplicate cells and edge identities after all expected partitions complete.

    Args:
        partition_candidates: Candidate records keyed by their completed input partition.
        expected_partition_keys: All partition keys expected for the run.

    Returns:
        One candidate per canonical H3 ID, sorted by H3 integer value, with unique eligible
        intersecting edges sorted by source ID and source OID.

    Raises:
        ValueError: If expected partitions are missing/extra or duplicate cells disagree on
            H3 resolution.
    """
    expected_keys = set(expected_partition_keys)
    supplied_keys = set(partition_candidates)
    missing_keys = expected_keys - supplied_keys
    unexpected_keys = supplied_keys - expected_keys
    if missing_keys:
        raise ValueError(f"Missing expected partitions: {', '.join(sorted(missing_keys))}")
    if unexpected_keys:
        raise ValueError(f"Unexpected partitions: {', '.join(sorted(unexpected_keys))}")

    candidates_by_cell: dict[int, list[CellGeometryCandidate]] = {}
    for partition_key in sorted(expected_keys):
        for candidate in partition_candidates[partition_key]:
            canonical_id = canonical_h3_ids([candidate.h3_id])[0]
            candidates_by_cell.setdefault(canonical_id, []).append(candidate)

    reconciled: list[CellGeometryCandidate] = []
    for cell_id in canonical_h3_ids(candidates_by_cell):
        cell_candidates = candidates_by_cell[cell_id]
        resolutions = {candidate.resolution for candidate in cell_candidates}
        if len(resolutions) != 1:
            raise ValueError(f"Conflicting H3 resolutions for cell {cell_id}")

        edges_by_identity: dict[tuple[int, int], EdgeIntersectionEvidence] = {}
        for candidate in cell_candidates:
            for edge in candidate.intersecting_edges:
                edges_by_identity.setdefault((edge.source_id, edge.source_oid), edge)
        intersecting_edges = tuple(
            edges_by_identity[identity] for identity in sorted(edges_by_identity)
        )
        first_candidate = cell_candidates[0]
        reconciled.append(
            CellGeometryCandidate(
                h3_id=cell_id,
                resolution=first_candidate.resolution,
                cell_geometry=first_candidate.cell_geometry,
                centroid_geometry=first_candidate.centroid_geometry,
                intersecting_edges=intersecting_edges,
                eligibility_reason=(
                    "eligible edge intersects cell within AOI"
                    if intersecting_edges
                    else "no eligible intersecting edge within AOI"
                ),
            )
        )
    logger.info(
        "Reconciled %s unique H3 cells across %s input partitions",
        len(reconciled),
        len(expected_keys),
    )
    return reconciled


def finalize_eligibility_results(
    run_state: EligibilityRunState,
    results: list[CellEligibilityResult],
    snap_tolerance_m: float,
) -> list[CellEligibilityResult]:
    """Validate the solvable-only handoff and atomically decide run completion.

    No partial handoff is returned on a failed cap or incomplete partition set.

    Args:
        run_state: Persisted logical run state after staged-part reconciliation.
        results: Globally reconciled eligibility rows.
        snap_tolerance_m: Configured maximum representative snap distance in meters.

    Returns:
        Validated, unique solvable-cell rows for a later OD-planning stage.

    Raises:
        ValueError: If partitions are incomplete, H3 IDs are duplicated, a solvable row is
            invalid, or the unique solvable count exceeds the run hard cap.
    """
    if run_state.status != RunStatus.PROCESSING:
        raise ValueError(f"Cannot finalize a {run_state.status.value} run")
    if any(status.value != "reconciled" for status in run_state.partition_status.values()):
        run_state.status = RunStatus.FAILED_INCOMPLETE
        raise ValueError("Cannot complete a run with unreconciled partitions")

    try:
        solvable_results = validated_solvable_results(results, snap_tolerance_m)
    except ValueError:
        run_state.status = RunStatus.FAILED_INCOMPLETE
        raise
    normalized_ids = [canonical_h3_ids([result.h3_id])[0] for result in solvable_results]
    if len(normalized_ids) != len(set(normalized_ids)):
        run_state.status = RunStatus.FAILED_INCOMPLETE
        raise ValueError("Duplicate H3 cells remain after eligibility reconciliation")

    finalize_run(run_state, unique_solvable_cell_count=len(normalized_ids))
    if run_state.status != RunStatus.COMPLETE:
        raise ValueError(
            "Unique solvable cell count exceeds total output hard cap; run remains incomplete"
        )
    return solvable_results
