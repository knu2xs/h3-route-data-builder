"""Portable orchestration of geometry-stage cell evidence."""

from collections.abc import Iterable, Mapping
from typing import Any

from .cells import canonical_h3_ids
from .models import (
    CellEligibilityResult,
    CellGeometryCandidate,
    EdgeEvidence,
    EdgeIntersectionEvidence,
    EligibilityStatus,
    NetworkLocation,
)
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


def build_geometry_candidates(
    cell_geometries: Mapping[str, Any],
    network_edges: Iterable[Any],
    aoi_geometry: Any,
    resolution: int,
) -> list[CellGeometryCandidate]:
    """Build deterministic per-cell eligible-edge intersection evidence.

    ArcPy geometry imports occur inside this operation so the eligibility package and its
    non-spatial models remain importable without ArcPy.

    Args:
        cell_geometries: Canonical H3 IDs mapped to projected ArcPy cell polygons.
        network_edges: Network edge records with projected geometry and eligibility decision.
        aoi_geometry: Valid projected ArcPy AOI polygon used to limit edge evidence.
        resolution: Configured H3 resolution.

    Returns:
        One candidate record for each unique canonical H3 ID, sorted by H3 integer order.

    Raises:
        ValueError: If cell IDs are invalid or a supplied cell geometry is missing.
    """
    from h3_route_data_builder.network.geometry import (
        clip_edge_to_aoi,
        geometry_intersection,
    )
    import arcpy

    canonical_ids = canonical_h3_ids(cell_geometries)
    canonical_geometries = {
        cell_id.lower(): geometry for cell_id, geometry in cell_geometries.items()
    }
    eligible_edges = sorted(
        (
            edge
            for edge in network_edges
            if edge.decision.eligibility_status == "eligible"
        ),
        key=lambda edge: (edge.source_id, edge.source_oid, edge.source_name),
    )

    candidates: list[CellGeometryCandidate] = []
    for cell_id in canonical_ids:
        cell_geometry = canonical_geometries.get(cell_id)
        if cell_geometry is None:
            raise ValueError(f"Missing geometry for H3 cell {cell_id}")
        intersections: list[EdgeIntersectionEvidence] = []
        for edge in eligible_edges:
            in_aoi = clip_edge_to_aoi(edge.geometry_working, aoi_geometry)
            matching_geometry = None
            for geometry in (in_aoi.lines, in_aoi.points):
                if geometry is None:
                    continue
                cell_intersection = geometry_intersection(cell_geometry, geometry)
                matching_geometry = cell_intersection.lines or cell_intersection.points
                if matching_geometry is not None:
                    break
            if matching_geometry is not None:
                intersections.append(
                    EdgeIntersectionEvidence(
                        source_id=edge.source_id,
                        source_oid=edge.source_oid,
                        network_edge_geometry=edge.geometry_working,
                        in_aoi_intersection_geometry=matching_geometry,
                        allowed_directions=edge.decision.allowed_directions,
                        eligibility_reason=edge.decision.reason,
                    )
                )
        candidates.append(
            CellGeometryCandidate(
                h3_id_hex=cell_id,
                resolution=resolution,
                cell_geometry=cell_geometry,
                centroid_geometry=arcpy.PointGeometry(
                    cell_geometry.centroid,
                    cell_geometry.spatialReference,
                ),
                intersecting_edges=tuple(intersections),
                eligibility_reason=(
                    "eligible edge intersects cell within AOI"
                    if intersections
                    else "no eligible intersecting edge within AOI"
                ),
            )
        )
    eligible_count = sum(
        candidate.has_eligible_intersection for candidate in candidates
    )
    logger.info(
        "Built geometry evidence for %s cells; %s have eligible edge intersections",
        len(candidates),
        eligible_count,
    )
    return candidates


def build_cell_eligibility_result(
    candidate: CellGeometryCandidate,
    representative: NetworkLocation | None,
    snap_tolerance_m: float,
    policy_evidence: dict[str, Any],
    build_fingerprint: str,
) -> CellEligibilityResult:
    """Convert one geometry candidate to an auditable eligibility result.

    A row is `solvable` only when an eligible intersecting edge exists and its representative
    is on one of those edges with a valid snap distance. Network Analyst location calculation
    is performed by the ArcPy network adapter before calling this function.

    Args:
        candidate: Reconciled H3 geometry and eligible-edge evidence.
        representative: Network-validated representative, if available.
        snap_tolerance_m: Configured maximum representative snap distance.
        policy_evidence: Serializable CRS, travel mode, restriction, intersection, and
            representative policy values for this build.
        build_fingerprint: Stable fingerprint of inputs, schema, software, and policy.

    Returns:
        Cell result marked solvable only when all network evidence is valid.

    Raises:
        ValueError: If tolerance is negative or fingerprint is missing.
    """
    if snap_tolerance_m < 0:
        raise ValueError("snap_tolerance_m must be non-negative")
    if not build_fingerprint:
        raise ValueError("build_fingerprint must be non-empty")

    edge_evidence = tuple(
        EdgeEvidence(
            source_id=edge.source_id,
            source_oid=edge.source_oid,
            eligibility_status="eligible",
            reason=edge.eligibility_reason,
            travel_direction=",".join(edge.allowed_directions),
        )
        for edge in sorted(
            candidate.intersecting_edges,
            key=lambda item: (item.source_id, item.source_oid),
        )
    )
    unique_edge_evidence = {
        (edge.source_id, edge.source_oid): edge for edge in edge_evidence
    }
    edge_evidence = tuple(
        unique_edge_evidence[key] for key in sorted(unique_edge_evidence)
    )
    ineligible_reason: str | None = None
    if not edge_evidence:
        ineligible_reason = "no eligible intersecting edge within AOI"
    elif representative is None:
        ineligible_reason = "no valid on-network representative"
    elif (
        representative.source_id,
        representative.source_oid,
    ) not in unique_edge_evidence:
        ineligible_reason = (
            "representative does not match an eligible intersecting edge"
        )
    elif representative.snap_distance_m > snap_tolerance_m:
        ineligible_reason = "representative snap distance exceeds configured tolerance"

    status = (
        EligibilityStatus.INELIGIBLE
        if ineligible_reason
        else EligibilityStatus.SOLVABLE
    )
    reason = (
        ineligible_reason
        or "eligible edge intersects cell and representative is validated"
    )
    result = CellEligibilityResult(
        h3_id_hex=candidate.h3_id_hex,
        resolution=candidate.resolution,
        eligibility_status=status,
        eligibility_reason=reason,
        intersecting_edge_count=len(edge_evidence),
        representative=representative if status == EligibilityStatus.SOLVABLE else None,
        edge_evidence=edge_evidence,
        policy_evidence=policy_evidence,
        build_fingerprint=build_fingerprint,
        cell_geometry=candidate.cell_geometry,
        centroid_geometry=candidate.centroid_geometry,
    )
    if result.eligibility_status == EligibilityStatus.INELIGIBLE:
        logger.warning(
            "H3 cell %s excluded: %s", result.h3_id_hex, result.eligibility_reason
        )
    else:
        logger.debug(
            "H3 cell %s has validated representative evidence", result.h3_id_hex
        )
    return result
