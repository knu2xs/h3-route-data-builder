"""Tests for portable H3 eligibility invariants."""

import pytest
from h3.api import basic_int as h3

from h3_route_data_builder.eligibility.cells import (
    canonical_h3_ids,
    h3_candidate_ids,
    h3_cell_boundary,
)
from h3_route_data_builder.eligibility.engine import build_cell_eligibility_result
from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    CellGeometryCandidate,
    EdgeIntersectionEvidence,
    EligibilityStatus,
    NetworkLocation,
    validated_solvable_results,
)


def make_solvable_result(
    h3_id: int = 617700169958293503,
    intersecting_edge_count: int = 1,
    representative: NetworkLocation | None = None,
) -> CellEligibilityResult:
    """Create a minimal result for testing handoff validation."""
    if representative is None:
        representative = NetworkLocation(
            x=0.0,
            y=0.0,
            source_id=1,
            source_oid=10,
            pos_along=0.5,
            side_of_edge=1,
            snap_distance_m=0.0,
        )
    return CellEligibilityResult(
        h3_id=h3_id,
        resolution=9,
        eligibility_status=EligibilityStatus.SOLVABLE,
        eligibility_reason="intersects eligible edge",
        intersecting_edge_count=intersecting_edge_count,
        representative=representative,
    )


def test_edge_less_cell_is_not_admitted_to_solvable_handoff() -> None:
    result = make_solvable_result(intersecting_edge_count=0)

    with pytest.raises(ValueError, match="no eligible intersecting edge"):
        validated_solvable_results([result], snap_tolerance_m=0.01)


def test_solvable_cell_requires_a_representative() -> None:
    result = make_solvable_result(representative=None)
    result = CellEligibilityResult(
        h3_id=result.h3_id,
        resolution=result.resolution,
        eligibility_status=result.eligibility_status,
        eligibility_reason=result.eligibility_reason,
        intersecting_edge_count=result.intersecting_edge_count,
        representative=None,
    )

    with pytest.raises(ValueError, match="no representative"):
        validated_solvable_results([result], snap_tolerance_m=0.01)


def test_ineligible_cell_is_excluded_from_handoff() -> None:
    result = make_solvable_result()
    ineligible = CellEligibilityResult(
        h3_id=617700169958031359,
        resolution=9,
        eligibility_status=EligibilityStatus.INELIGIBLE,
        eligibility_reason="no eligible intersecting edge",
        intersecting_edge_count=0,
    )

    assert validated_solvable_results([ineligible, result], snap_tolerance_m=0.01) == [result]


def test_representative_over_snap_tolerance_is_rejected() -> None:
    representative = NetworkLocation(
        x=0.0,
        y=0.0,
        source_id=1,
        source_oid=10,
        pos_along=0.5,
        side_of_edge=1,
        snap_distance_m=0.02,
    )

    with pytest.raises(ValueError, match="exceeds snap tolerance"):
        validated_solvable_results(
            [make_solvable_result(representative=representative)],
            snap_tolerance_m=0.01,
        )


def test_h3_cell_ids_are_canonical_deduplicated_and_sorted() -> None:
    first = h3.latlng_to_cell(37.775, -122.418, 9)
    second = h3.latlng_to_cell(37.78, -122.42, 9)

    result = canonical_h3_ids([second, first, second])

    assert result == sorted({first, second})


def test_invalid_h3_cell_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid H3 cell ID"):
        canonical_h3_ids(["not-an-h3-cell"])


@pytest.mark.parametrize("resolution", [8, 10, True, 9.0, None])
def test_eligibility_result_rejects_inconsistent_declared_resolution(
    resolution: object,
) -> None:
    with pytest.raises(ValueError, match="resolution"):
        CellEligibilityResult(
            h3_id=617700169958293503,
            resolution=resolution,
            eligibility_status=EligibilityStatus.INELIGIBLE,
            eligibility_reason="no edge",
            intersecting_edge_count=0,
        )


@pytest.mark.parametrize("cell_id", ["8928308280fffff", True, 1.0, None, 0])
def test_eligibility_result_rejects_noncanonical_identity(cell_id: object) -> None:
    with pytest.raises(ValueError, match="H3"):
        make_solvable_result(h3_id=cell_id)


def test_cell_becomes_solvable_only_with_matching_validated_representative() -> None:
    edge = EdgeIntersectionEvidence(1, 10, None, None)
    candidate = CellGeometryCandidate(
        h3_id=617700169958293503,
        resolution=9,
        cell_geometry=None,
        centroid_geometry=None,
        intersecting_edges=(edge,),
        eligibility_reason="eligible edge intersects cell within AOI",
    )
    representative = NetworkLocation(
        x=1.0,
        y=1.0,
        source_id=1,
        source_oid=10,
        pos_along=0.5,
        side_of_edge=1,
        snap_distance_m=0.0,
    )

    result = build_cell_eligibility_result(
        candidate,
        representative,
        snap_tolerance_m=0.01,
        policy_evidence={"travel_mode": "Driving Time"},
        build_fingerprint="fingerprint",
    )

    assert result.eligibility_status == EligibilityStatus.SOLVABLE
    assert result.intersecting_edge_count == 1
    assert result.representative == representative
    assert result.build_fingerprint == "fingerprint"


def test_cell_with_representative_on_wrong_edge_is_ineligible() -> None:
    candidate = CellGeometryCandidate(
        h3_id=617700169958293503,
        resolution=9,
        cell_geometry=None,
        centroid_geometry=None,
        intersecting_edges=(EdgeIntersectionEvidence(1, 10, None, None),),
        eligibility_reason="eligible edge intersects cell within AOI",
    )
    representative = NetworkLocation(1, 1, 1, 99, 0.5, 1, 0.0)

    result = build_cell_eligibility_result(candidate, representative, 0.01, {}, "fingerprint")

    assert result.eligibility_status == EligibilityStatus.INELIGIBLE
    assert result.representative is None


def test_cell_without_intersecting_edge_stays_ineligible() -> None:
    candidate = CellGeometryCandidate(
        h3_id=617700169958293503,
        resolution=9,
        cell_geometry=None,
        centroid_geometry=None,
        intersecting_edges=(),
        eligibility_reason="no eligible intersecting edge within AOI",
    )

    result = build_cell_eligibility_result(candidate, None, 0.01, {}, "fingerprint")

    assert result.eligibility_status == EligibilityStatus.INELIGIBLE
    assert result.intersecting_edge_count == 0


def test_h3_bbox_overlap_cover_includes_pentagon_and_adjacent_cell() -> None:
    pentagon = h3.get_pentagons(4)[0]
    adjacent_cell = next(cell for cell in h3.grid_disk(pentagon, 1) if cell != pentagon)

    polygons = []
    for cell_id in (pentagon, adjacent_cell):
        ring = [list(point) for point in h3_cell_boundary(cell_id)]
        ring.append(ring[0])
        polygons.append([ring])
    aoi_geojson = {"type": "MultiPolygon", "coordinates": polygons}

    candidate_ids = h3_candidate_ids(aoi_geojson, resolution=4)

    assert pentagon in candidate_ids
    assert adjacent_cell in candidate_ids
    assert len(candidate_ids) == len(set(candidate_ids))
