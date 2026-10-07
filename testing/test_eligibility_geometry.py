"""ArcPy geometry acceptance tests for AOI and edge intersection behavior."""

from typing import Any

import pytest
import h3

from h3_route_data_builder.network.geometry import (
    candidate_h3_cells_for_aoi,
    cell_result_geometries_wkb,
    h3_cell_polygon,
)
from h3_route_data_builder.network.geometry import (
    clip_edge_to_aoi,
    intersects_inclusive,
    project_geometry,
    validate_aoi_geometry,
)
from h3_route_data_builder.eligibility.engine import build_geometry_candidates
from h3_route_data_builder.network.eligibility import (
    EdgeEligibilityDecision,
    NetworkEdgeRecord,
)
from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    EligibilityStatus,
    NetworkLocation,
)

TEST_PROJECTED_CRS = (
    'PROJCS["Eligibility Test CRS",GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Mercator_1SP"],PARAMETER["False_Easting",0],'
    'PARAMETER["False_Northing",0],PARAMETER["Central_Meridian",0],'
    'PARAMETER["Scale_Factor",1],PARAMETER["Latitude_Of_Origin",0],'
    'UNIT["Meter",1],AXIS["X",EAST],AXIS["Y",NORTH]]'
)


def make_spatial_reference(arcpy_module: Any) -> Any:
    """Create a projected test CRS without relying on a hard-coded WKID."""
    return arcpy_module.SpatialReference(text=TEST_PROJECTED_CRS)


def make_polygon(
    arcpy_module: Any, coordinates: list[tuple[float, float]], spatial_reference: Any
) -> Any:
    """Create a closed ArcPy polygon from coordinate pairs."""
    points = arcpy_module.Array(
        [
            arcpy_module.Point(x_coord, y_coord)
            for x_coord, y_coord in coordinates + [coordinates[0]]
        ]
    )
    return arcpy_module.Polygon(points, spatial_reference)


def make_polyline(
    arcpy_module: Any,
    parts: list[list[tuple[float, float]]],
    spatial_reference: Any,
) -> Any:
    """Create a single- or multipart ArcPy polyline."""
    part_array = arcpy_module.Array()
    for coordinates in parts:
        point_array = arcpy_module.Array(
            [arcpy_module.Point(x_coord, y_coord) for x_coord, y_coord in coordinates]
        )
        part_array.add(point_array)
    return arcpy_module.Polyline(part_array, spatial_reference)


@pytest.fixture
def projected_spatial_reference(arcpy_module: Any) -> Any:
    """Provide a local projected spatial reference for planar test geometry."""
    return make_spatial_reference(arcpy_module)


@pytest.fixture
def square_aoi(arcpy_module: Any, projected_spatial_reference: Any) -> Any:
    """Provide a square AOI for exact topology cases."""
    return make_polygon(
        arcpy_module,
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        projected_spatial_reference,
    )


def test_validate_aoi_accepts_valid_polygon(square_aoi: Any) -> None:
    assert validate_aoi_geometry(square_aoi).name != "Unknown"


def test_validate_aoi_rejects_unknown_spatial_reference(arcpy_module: Any) -> None:
    unknown_spatial_reference = arcpy_module.SpatialReference()
    aoi = make_polygon(
        arcpy_module, [(0, 0), (10, 0), (10, 10), (0, 10)], unknown_spatial_reference
    )

    with pytest.raises(ValueError, match="unknown spatial reference"):
        validate_aoi_geometry(aoi)


def test_validate_aoi_rejects_empty_polygon(
    arcpy_module: Any,
) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        validate_aoi_geometry(None)


def test_project_geometry_uses_explicit_target_spatial_reference(
    arcpy_module: Any,
    projected_spatial_reference: Any,
) -> None:
    source_reference = make_spatial_reference(arcpy_module)
    target_reference = make_spatial_reference(arcpy_module)
    geometry = make_polygon(
        arcpy_module, [(0, 0), (10, 0), (10, 10), (0, 10)], source_reference
    )

    projected = project_geometry(geometry, target_reference)

    assert projected.spatialReference.name == target_reference.name
    assert projected.area > 0


@pytest.mark.parametrize(
    ("line_coordinates", "expected"),
    [
        ([(-1, 5), (11, 5)], True),
        ([(-1, 5), (0, 5)], True),
        ([(0, 0), (10, 0)], True),
        ([(-1, -0.1), (11, -0.1)], False),
    ],
    ids=["crossing", "point-touch", "coincident-boundary", "nearby-no-touch"],
)
def test_inclusive_intersection_matches_topology(
    arcpy_module: Any,
    square_aoi: Any,
    projected_spatial_reference: Any,
    line_coordinates: list[tuple[float, float]],
    expected: bool,
) -> None:
    edge = make_polyline(arcpy_module, [line_coordinates], projected_spatial_reference)

    assert intersects_inclusive(square_aoi, edge) is expected


def test_inclusive_intersection_considers_every_multipart_edge_part(
    arcpy_module: Any,
    square_aoi: Any,
    projected_spatial_reference: Any,
) -> None:
    edge = make_polyline(
        arcpy_module,
        [[(-1, 5), (11, 5)], [(-1, 20), (11, 20)]],
        projected_spatial_reference,
    )

    assert intersects_inclusive(square_aoi, edge)


def test_clip_edge_to_aoi_returns_only_in_aoi_linework(
    arcpy_module: Any,
    square_aoi: Any,
    projected_spatial_reference: Any,
) -> None:
    edge = make_polyline(
        arcpy_module, [[(-5, 5), (15, 5)]], projected_spatial_reference
    )

    clipped = clip_edge_to_aoi(edge, square_aoi)

    assert clipped.lines is not None
    assert clipped.lines.extent.XMin == pytest.approx(0)
    assert clipped.lines.extent.XMax == pytest.approx(10)
    assert clipped.points is not None
    assert clipped.points.pointCount == 2


def test_pentagon_and_neighbor_cells_project_and_remain_in_candidate_cover(
    arcpy_module: Any,
    projected_spatial_reference: Any,
) -> None:
    pentagon = h3.get_pentagons(4)[0]
    adjacent_cell = next(cell for cell in h3.grid_disk(pentagon, 1) if cell != pentagon)
    pentagon_polygon = h3_cell_polygon(pentagon, projected_spatial_reference)
    adjacent_polygon = h3_cell_polygon(adjacent_cell, projected_spatial_reference)
    combined_aoi = pentagon_polygon.union(adjacent_polygon)

    candidate_ids = candidate_h3_cells_for_aoi(combined_aoi, resolution=4)

    assert pentagon in candidate_ids
    assert adjacent_cell in candidate_ids
    assert intersects_inclusive(pentagon_polygon, pentagon_polygon)
    assert intersects_inclusive(adjacent_polygon, adjacent_polygon)


def test_geometry_candidates_use_only_eligible_edges_inside_aoi(
    arcpy_module: Any,
    square_aoi: Any,
    projected_spatial_reference: Any,
) -> None:
    eligible_edge = NetworkEdgeRecord(
        source_id=1,
        source_oid=100,
        source_name="Streets",
        geometry_working=make_polyline(
            arcpy_module, [[(-1, 5), (11, 5)]], projected_spatial_reference
        ),
        decision=EdgeEligibilityDecision(
            "eligible", ("AlongDigitizedDirection",), "allowed"
        ),
    )
    restricted_edge = NetworkEdgeRecord(
        source_id=1,
        source_oid=101,
        source_name="Streets",
        geometry_working=make_polyline(
            arcpy_module, [[(-1, 2), (11, 2)]], projected_spatial_reference
        ),
        decision=EdgeEligibilityDecision("restricted", (), "restricted by travel mode"),
    )
    outside_cell = make_polygon(
        arcpy_module,
        [(20, 0), (30, 0), (30, 10), (20, 10)],
        projected_spatial_reference,
    )

    candidates = build_geometry_candidates(
        {"8928308280fffff": square_aoi, "8928308280bffff": outside_cell},
        [restricted_edge, eligible_edge],
        square_aoi,
        resolution=9,
    )

    by_id = {candidate.h3_id_hex: candidate for candidate in candidates}
    assert by_id["8928308280fffff"].has_eligible_intersection
    assert [
        edge.source_oid for edge in by_id["8928308280fffff"].intersecting_edges
    ] == [100]
    assert not by_id["8928308280bffff"].has_eligible_intersection


def test_geometry_candidate_evidence_is_clipped_to_the_cell(
    arcpy_module: Any,
    square_aoi: Any,
    projected_spatial_reference: Any,
) -> None:
    cell = make_polygon(
        arcpy_module,
        [(4, 4), (6, 4), (6, 6), (4, 6)],
        projected_spatial_reference,
    )
    edge = NetworkEdgeRecord(
        source_id=1,
        source_oid=100,
        source_name="Streets",
        geometry_working=make_polyline(
            arcpy_module, [[(-1, 5), (11, 5)]], projected_spatial_reference
        ),
        decision=EdgeEligibilityDecision(
            "eligible", ("AlongDigitizedDirection",), "allowed"
        ),
    )

    candidates = build_geometry_candidates(
        {"8928308280fffff": cell}, [edge], square_aoi, resolution=9
    )

    intersection_geometry = (
        candidates[0].intersecting_edges[0].in_aoi_intersection_geometry
    )
    assert intersection_geometry.extent.XMin == pytest.approx(4)
    assert intersection_geometry.extent.XMax == pytest.approx(6)


def test_cell_result_geometries_are_projected_to_storage_crs_wkb(
    arcpy_module: Any,
    projected_spatial_reference: Any,
) -> None:
    cell_geometry = make_polygon(
        arcpy_module,
        [(-10, -10), (10, -10), (10, 10), (-10, 10)],
        projected_spatial_reference,
    )
    result = CellEligibilityResult(
        h3_id_hex="8928308280fffff",
        resolution=9,
        eligibility_status=EligibilityStatus.SOLVABLE,
        eligibility_reason="validated",
        intersecting_edge_count=1,
        representative=NetworkLocation(-5, 0, 1, 10, 0.25, 1, 0.0),
        build_fingerprint="fingerprint",
        cell_geometry=cell_geometry,
        centroid_geometry=arcpy_module.PointGeometry(
            cell_geometry.centroid,
            projected_spatial_reference,
        ),
    )
    storage_spatial_reference = arcpy_module.SpatialReference("GCS_WGS_1984")

    geometries = cell_result_geometries_wkb([result], storage_spatial_reference)

    cell_wkb, centroid_wkb, representative_wkb = geometries[result.h3_id_hex]
    assert (
        arcpy_module.FromWKB(cell_wkb, storage_spatial_reference).type.casefold()
        == "polygon"
    )
    assert (
        arcpy_module.FromWKB(centroid_wkb, storage_spatial_reference).type.casefold()
        == "point"
    )
    assert (
        arcpy_module.FromWKB(
            representative_wkb, storage_spatial_reference
        ).type.casefold()
        == "point"
    )
