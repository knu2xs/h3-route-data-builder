"""ArcPy acceptance tests for AOI-to-surrounding geometry scope."""

import pytest

arcpy = pytest.importorskip("arcpy")
h3 = pytest.importorskip("h3")

from h3_route_data_builder.od.candidates import build_candidate_plan
from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    EligibilityStatus,
    NetworkLocation,
)
from h3_route_data_builder.network.geometry import build_aoi_candidate_scope
from h3_route_data_builder.od.models import CandidateMode, SolvableCell


def polygon(xmin: float, ymin: float, xmax: float, ymax: float) -> arcpy.Geometry:
    """Create a WGS 84 polygon test fixture."""
    spatial_reference = arcpy.SpatialReference(4326)
    points = arcpy.Array(
        [
            arcpy.Point(xmin, ymin),
            arcpy.Point(xmax, ymin),
            arcpy.Point(xmax, ymax),
            arcpy.Point(xmin, ymax),
            arcpy.Point(xmin, ymin),
        ]
    )
    return arcpy.Polygon(points, spatial_reference)


def cell_result(
    latitude: float,
    longitude: float,
    *,
    solvable: bool = True,
) -> CellEligibilityResult:
    """Construct a geometry-backed eligibility result."""
    cell_id = h3.latlng_to_cell(latitude, longitude, 9)
    boundary = h3.cell_to_boundary(cell_id)
    cell_polygon = arcpy.Polygon(
        arcpy.Array([arcpy.Point(lon, lat) for lat, lon in (*boundary, boundary[0])]),
        arcpy.SpatialReference(4326),
    )
    return CellEligibilityResult(
        h3_id_hex=cell_id,
        resolution=9,
        eligibility_status=(
            EligibilityStatus.SOLVABLE if solvable else EligibilityStatus.INELIGIBLE
        ),
        eligibility_reason="test",
        intersecting_edge_count=1 if solvable else 0,
        representative=(
            NetworkLocation(
                x=longitude,
                y=latitude,
                source_id=1,
                source_oid=1,
                pos_along=0.0,
                side_of_edge=0,
                snap_distance_m=0.0,
            )
            if solvable
            else None
        ),
        cell_geometry=cell_polygon,
    )


def test_surrounding_scope_includes_boundary_touching_cells_and_only_solvable_endpoints() -> (
    None
):
    inside = cell_result(0.0, 0.0)
    surrounding = cell_result(0.0, 0.002)
    aoi = polygon(
        -0.001,
        -0.001,
        surrounding.cell_geometry.extent.XMin,
        0.001,
    )
    ineligible = cell_result(0.0, 0.01, solvable=False)

    scope = build_aoi_candidate_scope(
        aoi,
        [inside, surrounding, ineligible],
        CandidateMode.AOI_TO_SURROUNDING,
        reach_distance_m=1000.0,
        resolution=9,
    )

    assert set(scope.origin_ids) == {inside.h3_id_hex, surrounding.h3_id_hex}
    assert inside.h3_id_hex in scope.destination_ids
    assert surrounding.h3_id_hex in scope.destination_ids
    assert ineligible.h3_id_hex not in scope.origin_ids
    assert ineligible.h3_id_hex not in scope.destination_ids
    assert scope.maximum_origin_offset_m > 0.0
    assert scope.expanded_aoi.disjoint(aoi) is False


def test_nearest_aoi_offset_is_not_centroid_distance_and_expands_by_offset_plus_reach() -> (
    None
):
    aoi = polygon(-0.001, -0.001, 0.001, 0.001)
    origin = cell_result(0.0, 0.0015)

    scope = build_aoi_candidate_scope(
        aoi,
        [origin],
        CandidateMode.AOI_TO_SURROUNDING,
        reach_distance_m=1000.0,
        resolution=9,
    )

    assert scope.maximum_origin_offset_m == pytest.approx(55.66, abs=1.0)
    assert scope.expanded_aoi.disjoint(aoi) is False


def test_invalid_reach_fails_and_declared_source_crs_is_projected_to_wgs84() -> None:
    aoi = polygon(-0.001, -0.001, 0.001, 0.001)
    with pytest.raises(ValueError, match="reach_distance_m"):
        build_aoi_candidate_scope(
            aoi, [], CandidateMode.AOI_TO_SURROUNDING, -1.0, resolution=9
        )

    web_mercator = arcpy.SpatialReference(3857)
    projected_aoi = polygon(-0.001, -0.001, 0.001, 0.001).projectAs(web_mercator)
    scope = build_aoi_candidate_scope(
        projected_aoi, [], CandidateMode.AOI_TO_SURROUNDING, 100.0, resolution=9
    )
    assert scope.aoi_geometry.spatialReference.factoryCode == 4326


def test_destination_only_cells_do_not_get_self_pairs() -> None:
    aoi = polygon(-0.001, -0.001, 0.001, 0.001)
    inside = cell_result(0.0, 0.0)
    outside = cell_result(0.0, 0.01)

    scope = build_aoi_candidate_scope(
        aoi,
        [inside, outside],
        CandidateMode.AOI_TO_SURROUNDING,
        reach_distance_m=2000.0,
        resolution=9,
    )
    portable_cells = [
        SolvableCell(
            h3_id_hex=result.h3_id_hex,
            resolution=result.resolution,
            eligibility_status=result.eligibility_status,
            representative=(result.representative.x, result.representative.y),
            cell_geometry=result.cell_geometry,
        )
        for result in (inside, outside)
    ]
    plan = build_candidate_plan(portable_cells, scope, 2000.0, "m")

    assert outside.h3_id_hex in scope.destination_ids
    assert outside.h3_id_hex not in scope.origin_ids
    assert all(
        pair.origin_h3_id != pair.destination_h3_id
        for pair in plan.pairs
        if pair.destination_h3_id == outside.h3_id_hex
    )


def test_aoi_only_geometry_uses_identical_origin_and_destination_sets() -> None:
    aoi = polygon(-0.001, -0.001, 0.001, 0.001)
    inside = cell_result(0.0, 0.0)
    outside = cell_result(0.0, 0.01)

    scope = build_aoi_candidate_scope(
        aoi,
        [inside, outside],
        CandidateMode.AOI_ONLY,
        reach_distance_m=1000.0,
        resolution=9,
    )

    assert scope.origin_ids == (inside.h3_id_hex,)
    assert scope.destination_ids == scope.origin_ids
