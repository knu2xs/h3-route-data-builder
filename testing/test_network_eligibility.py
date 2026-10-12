"""Tests for fail-closed Network Analyst edge eligibility."""

import pytest
from typing import Any

from h3_route_data_builder.network.eligibility import (
    EdgeEligibilityDecision,
    EdgeEvaluator,
    NetworkAttributeDefinition,
    NetworkEdgeRecord,
    classify_edge_directions,
    required_edge_fields,
)
from h3_route_data_builder.network.geometry import GeometryIntersection
from h3_route_data_builder.network.representatives import rank_representative_candidates
from h3_route_data_builder.network.locations import locate_representative_candidates
from h3_route_data_builder.eligibility.models import EdgeIntersectionEvidence
from h3_route_data_builder.network.representatives import RepresentativeCandidate

TEST_PROJECTED_CRS = (
    'PROJCS["Eligibility Test CRS",GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Mercator_1SP"],PARAMETER["False_Easting",0],'
    'PARAMETER["False_Northing",0],PARAMETER["Central_Meridian",0],'
    'PARAMETER["Scale_Factor",1],PARAMETER["Latitude_Of_Origin",0],'
    'UNIT["Meter",1],AXIS["X",EAST],AXIS["Y",NORTH]]'
)


def make_projected_line(
    arcpy_module: Any,
    coordinates: list[tuple[float, float]],
) -> Any:
    """Create an ArcPy line in the local projected test coordinate system."""
    spatial_reference = arcpy_module.SpatialReference(text=TEST_PROJECTED_CRS)
    points = arcpy_module.Array(
        [arcpy_module.Point(x_coord, y_coord) for x_coord, y_coord in coordinates]
    )
    return arcpy_module.Polyline(points, spatial_reference)


def make_evaluator(
    source_name: str,
    direction: str,
    expression: str,
    evaluator_type: str = "Field",
) -> EdgeEvaluator:
    """Construct one source-specific network evaluator for tests."""
    return EdgeEvaluator(
        source_name=source_name,
        edge_direction=direction,
        evaluator_type=evaluator_type,
        expression=expression,
    )


def make_network_attributes(
    direction_fields: tuple[str, str] = ("FT_TRAVEL_DIRECTION", "TF_TRAVEL_DIRECTION"),
    restriction_fields: tuple[str, str] = ("FT_RST_AUTOMOBILES", "TF_RST_AUTOMOBILES"),
    evaluator_type: str = "Field",
) -> dict[str, NetworkAttributeDefinition]:
    """Build synthetic Travel Direction and automobile restriction metadata."""
    return {
        "Travel Direction": NetworkAttributeDefinition(
            name="Travel Direction",
            usage_type="Descriptor",
            evaluators=(
                make_evaluator(
                    "Streets",
                    "AlongDigitizedDirection",
                    f"!{direction_fields[0]}! != 'N'",
                    evaluator_type,
                ),
                make_evaluator(
                    "Streets",
                    "AgainstDigitizedDirection",
                    f"!{direction_fields[1]}! != 'N'",
                    evaluator_type,
                ),
            ),
        ),
        "Driving an Automobile": NetworkAttributeDefinition(
            name="Driving an Automobile",
            usage_type="Restriction",
            evaluators=(
                make_evaluator(
                    "Streets",
                    "AlongDigitizedDirection",
                    f"!{restriction_fields[0]}! == 'Y'",
                ),
                make_evaluator(
                    "Streets",
                    "AgainstDigitizedDirection",
                    f"!{restriction_fields[1]}! == 'Y'",
                ),
            ),
        ),
    }


def make_travel_mode(restriction_usage: int = -1) -> dict[str, object]:
    """Build a minimal travel mode containing one active restriction."""
    return {
        "restrictionAttributeNames": ["Driving an Automobile"],
        "attributeParameterValues": [
            {
                "attributeName": "Driving an Automobile",
                "parameterName": "Restriction Usage",
                "value": restriction_usage,
            }
        ],
    }


def test_one_way_edge_is_eligible_only_in_allowed_direction() -> None:
    fields = {
        "FT_TRAVEL_DIRECTION": "Y",
        "TF_TRAVEL_DIRECTION": "N",
        "FT_RST_AUTOMOBILES": "N",
        "TF_RST_AUTOMOBILES": "N",
    }

    decision = classify_edge_directions(
        "Streets", fields, make_network_attributes(), make_travel_mode()
    )

    assert decision.eligibility_status == "eligible"
    assert decision.allowed_directions == ("AlongDigitizedDirection",)


def test_active_prohibited_evaluator_blocks_matching_direction() -> None:
    fields = {
        "FT_TRAVEL_DIRECTION": "Y",
        "TF_TRAVEL_DIRECTION": "Y",
        "FT_RST_AUTOMOBILES": "Y",
        "TF_RST_AUTOMOBILES": "N",
    }

    decision = classify_edge_directions(
        "Streets", fields, make_network_attributes(), make_travel_mode(-1)
    )

    assert decision.eligibility_status == "eligible"
    assert decision.allowed_directions == ("AgainstDigitizedDirection",)


@pytest.mark.parametrize("avoid_usage", [2, 5])
def test_avoid_usage_does_not_make_edge_non_traversable(avoid_usage: int) -> None:
    fields = {
        "FT_TRAVEL_DIRECTION": "Y",
        "TF_TRAVEL_DIRECTION": "Y",
        "FT_RST_AUTOMOBILES": "Y",
        "TF_RST_AUTOMOBILES": "Y",
    }

    decision = classify_edge_directions(
        "Streets", fields, make_network_attributes(), make_travel_mode(avoid_usage)
    )

    assert decision.eligibility_status == "eligible"
    assert decision.allowed_directions == (
        "AlongDigitizedDirection",
        "AgainstDigitizedDirection",
    )


def test_required_edge_fields_include_direction_and_prohibited_restrictions_only() -> (
    None
):
    attributes = make_network_attributes()
    attributes["Avoid Private Roads"] = NetworkAttributeDefinition(
        name="Avoid Private Roads",
        usage_type="Restriction",
        evaluators=(
            make_evaluator(
                "Streets", "AlongDigitizedDirection", "!PUBLIC_ROAD! == 'N'"
            ),
        ),
    )
    attributes["Turn Only Prohibition"] = NetworkAttributeDefinition(
        name="Turn Only Prohibition",
        usage_type="Restriction",
        evaluators=(
            make_evaluator("RestrictedTurns", None, "!TURN_RESTRICTED! == 'Y'"),
        ),
    )
    travel_mode = {
        "restrictionAttributeNames": ["Driving an Automobile", "Avoid Private Roads"],
        "attributeParameterValues": [
            {
                "attributeName": "Driving an Automobile",
                "parameterName": "Restriction Usage",
                "value": -1,
            },
            {
                "attributeName": "Avoid Private Roads",
                "parameterName": "Restriction Usage",
                "value": 2,
            },
        ],
    }

    fields = required_edge_fields("Streets", attributes, travel_mode)

    assert fields == [
        "FT_RST_AUTOMOBILES",
        "FT_TRAVEL_DIRECTION",
        "TF_RST_AUTOMOBILES",
        "TF_TRAVEL_DIRECTION",
    ]


def test_unsupported_evaluator_fails_closed() -> None:
    fields = {
        "FT_TRAVEL_DIRECTION": "Y",
        "TF_TRAVEL_DIRECTION": "Y",
        "FT_RST_AUTOMOBILES": "N",
        "TF_RST_AUTOMOBILES": "N",
    }

    decision = classify_edge_directions(
        "Streets",
        fields,
        make_network_attributes(evaluator_type="Script"),
        make_travel_mode(),
    )

    assert decision.eligibility_status == "undetermined"
    assert "unsupported" in decision.reason.lower()


def test_missing_evaluator_field_fails_closed() -> None:
    fields = {
        "FT_TRAVEL_DIRECTION": "Y",
        "TF_TRAVEL_DIRECTION": "Y",
        "FT_RST_AUTOMOBILES": "N",
    }

    decision = classify_edge_directions(
        "Streets", fields, make_network_attributes(), make_travel_mode()
    )

    assert decision.eligibility_status == "undetermined"
    assert "missing" in decision.reason.lower()


def test_malformed_field_expression_fails_closed() -> None:
    attributes = make_network_attributes()
    attributes["Travel Direction"] = NetworkAttributeDefinition(
        name="Travel Direction",
        usage_type="Descriptor",
        evaluators=(
            make_evaluator("Streets", "AlongDigitizedDirection", "__import__('os')"),
            make_evaluator("Streets", "AgainstDigitizedDirection", "__import__('os')"),
        ),
    )

    decision = classify_edge_directions(
        "Streets",
        {
            "FT_TRAVEL_DIRECTION": "Y",
            "TF_TRAVEL_DIRECTION": "Y",
            "FT_RST_AUTOMOBILES": "N",
            "TF_RST_AUTOMOBILES": "N",
        },
        attributes,
        make_travel_mode(),
    )

    assert decision.eligibility_status == "undetermined"
    assert decision.reason


def test_representative_candidates_tie_break_by_source_id_and_oid(arcpy_module) -> None:
    centroid = arcpy_module.PointGeometry(
        arcpy_module.Point(5, 5),
        arcpy_module.SpatialReference(text=TEST_PROJECTED_CRS),
    )
    lower_source_line = make_projected_line(arcpy_module, [(0, 4), (10, 4)])
    lower_oid_line = make_projected_line(arcpy_module, [(0, 6), (10, 6)])
    intersections = [
        EdgeIntersectionEvidence(2, 1, lower_source_line, lower_source_line),
        EdgeIntersectionEvidence(1, 9, lower_oid_line, lower_oid_line),
        EdgeIntersectionEvidence(1, 3, lower_oid_line, lower_oid_line),
    ]

    candidates = rank_representative_candidates(
        "8928308280fffff", centroid, intersections, snap_tolerance_m=0.001
    )

    assert [
        (candidate.source_id, candidate.source_oid) for candidate in candidates
    ] == [
        (1, 3),
        (1, 9),
        (2, 1),
    ]
    expected_distance = centroid.angleAndDistanceTo(
        candidates[0].point_geometry,
        "GEODESIC",
    )[1]
    assert [candidate.centroid_distance_m for candidate in candidates] == pytest.approx(
        [expected_distance, expected_distance, expected_distance]
    )


def test_representative_candidate_stays_on_in_aoi_intersection(arcpy_module) -> None:
    centroid = arcpy_module.PointGeometry(
        arcpy_module.Point(5, 5),
        arcpy_module.SpatialReference(text=TEST_PROJECTED_CRS),
    )
    network_line = make_projected_line(arcpy_module, [(-5, 5), (15, 5)])
    in_aoi_line = make_projected_line(arcpy_module, [(0, 5), (10, 5)])
    intersection = EdgeIntersectionEvidence(1, 1, network_line, in_aoi_line)

    candidates = rank_representative_candidates(
        "8928308280fffff", centroid, [intersection], snap_tolerance_m=0.001
    )

    assert len(candidates) == 1
    assert candidates[0].point_geometry.centroid.X == pytest.approx(5)
    assert candidates[0].point_geometry.centroid.Y == pytest.approx(5)
    assert candidates[0].snap_distance_m <= 0.001


def test_representative_candidates_outside_snap_tolerance_are_excluded(
    arcpy_module: Any,
) -> None:
    centroid = arcpy_module.PointGeometry(
        arcpy_module.Point(5, 5),
        arcpy_module.SpatialReference(text=TEST_PROJECTED_CRS),
    )
    network_edge = make_projected_line(arcpy_module, [(0, 5.1), (10, 5.1)])
    stale_intersection = make_projected_line(arcpy_module, [(0, 5), (10, 5)])
    intersection = EdgeIntersectionEvidence(1, 1, network_edge, stale_intersection)

    candidates = rank_representative_candidates(
        "8928308280fffff", centroid, [intersection], snap_tolerance_m=0.01
    )

    assert candidates == []


def make_representative_candidate(
    arcpy_module: Any,
    source_oid: int,
    distance_m: float,
) -> RepresentativeCandidate:
    """Build a minimal representative candidate for location tests."""
    spatial_reference = arcpy_module.SpatialReference(4326)
    point = arcpy_module.PointGeometry(arcpy_module.Point(-74, 40), spatial_reference)
    return RepresentativeCandidate(
        h3_id_hex="8928308280fffff",
        point_geometry=point,
        source_id=1,
        source_oid=source_oid,
        pos_along=0.5,
        centroid_distance_m=distance_m,
        snap_distance_m=0.0,
        right_of_edge=False,
    )


def test_location_mismatch_retries_next_ranked_edge_candidate(
    arcpy_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [
        make_representative_candidate(arcpy_module, source_oid=10, distance_m=1.0),
        make_representative_candidate(arcpy_module, source_oid=20, distance_m=2.0),
    ]

    def fake_calculate_locations(
        in_point_features: str,
        in_network_dataset: str,
        search_tolerance: str,
        travel_mode: str,
    ) -> None:
        arcpy_module.management.AddFields(
            in_point_features,
            [
                ["SourceID", "LONG"],
                ["SourceOID", "LONG"],
                ["PosAlong", "DOUBLE"],
                ["SideOfEdge", "SHORT"],
                ["DistanceToNetworkInMeters", "DOUBLE"],
            ],
        )
        with arcpy_module.da.UpdateCursor(
            in_point_features,
            [
                "candidate_index",
                "SourceID",
                "SourceOID",
                "PosAlong",
                "SideOfEdge",
                "DistanceToNetworkInMeters",
            ],
        ) as cursor:
            for row in cursor:
                row[1] = 1
                row[2] = 999 if row[0] == 0 else 20
                row[3] = 0.5
                row[4] = 1
                row[5] = 0.0
                cursor.updateRow(row)

    monkeypatch.setattr(arcpy_module, "Exists", lambda path: True)
    monkeypatch.setattr(arcpy_module.na, "CalculateLocations", fake_calculate_locations)

    location = locate_representative_candidates(
        candidates,
        network_dataset_path="synthetic-network",
        travel_mode="Driving Time",
        snap_tolerance_m=0.01,
    )

    assert location is not None
    assert location.source_oid == 20


def test_location_with_missing_network_fields_returns_none(
    arcpy_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = make_representative_candidate(
        arcpy_module, source_oid=10, distance_m=1.0
    )

    def fake_calculate_locations(
        in_point_features: str,
        in_network_dataset: str,
        search_tolerance: str,
        travel_mode: str,
    ) -> None:
        arcpy_module.management.AddFields(
            in_point_features,
            [
                ["SourceID", "LONG"],
                ["SourceOID", "LONG"],
                ["PosAlong", "DOUBLE"],
                ["SideOfEdge", "SHORT"],
                ["DistanceToNetworkInMeters", "DOUBLE"],
            ],
        )

    monkeypatch.setattr(arcpy_module, "Exists", lambda path: True)
    monkeypatch.setattr(arcpy_module.na, "CalculateLocations", fake_calculate_locations)

    location = locate_representative_candidates(
        [candidate],
        network_dataset_path="synthetic-network",
        travel_mode="Driving Time",
        snap_tolerance_m=0.01,
    )

    assert location is None
