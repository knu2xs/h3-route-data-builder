"""Deterministic on-network representative candidate selection."""

from dataclasses import dataclass
from typing import Any

import arcpy

from h3_route_data_builder.eligibility.models import EdgeIntersectionEvidence
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


@dataclass(frozen=True)
class RepresentativeCandidate:
    """Nearest on-network point candidate for one intersecting edge."""

    h3_id_hex: str
    point_geometry: arcpy.Geometry
    source_id: int
    source_oid: int
    pos_along: float
    centroid_distance_m: float
    snap_distance_m: float
    right_of_edge: bool


def rank_representative_candidates(
    h3_id_hex: str,
    cell_centroid: arcpy.Geometry,
    intersecting_edges: (
        list[EdgeIntersectionEvidence] | tuple[EdgeIntersectionEvidence, ...]
    ),
    snap_tolerance_m: float,
) -> list[RepresentativeCandidate]:
    """Build candidates only on eligible edge portions intersecting the cell in the AOI.

    Args:
        h3_id_hex: Canonical H3 cell identity.
        cell_centroid: Cell centroid in WGS 84 / EPSG:4326.
        intersecting_edges: Eligible in-AOI edge intersection evidence for the cell.
        snap_tolerance_m: Maximum allowed distance from the representative to its source edge.

    Returns:
        Candidates sorted by centroid distance, source ID, source OID, then edge measure.

    Raises:
        ValueError: If the centroid/reference is invalid or tolerance is negative.
    """
    if not h3_id_hex:
        raise ValueError("h3_id_hex must be non-empty")
    if snap_tolerance_m < 0:
        raise ValueError("snap_tolerance_m must be non-negative")
    if cell_centroid is None or cell_centroid.pointCount == 0:
        raise ValueError("cell_centroid must be non-empty")
    spatial_reference = cell_centroid.spatialReference
    if spatial_reference is None or spatial_reference.name == "Unknown":
        raise ValueError("cell_centroid has an unknown spatial reference")
    candidates: list[RepresentativeCandidate] = []
    for edge_evidence in intersecting_edges:
        edge_geometry = edge_evidence.network_edge_geometry
        intersection_geometry = edge_evidence.in_aoi_intersection_geometry
        if edge_geometry is None or intersection_geometry is None:
            continue
        _validate_matching_reference(cell_centroid, edge_geometry)
        _validate_matching_reference(cell_centroid, intersection_geometry)

        for point_on_intersection in _nearest_intersection_points(
            intersection_geometry,
            cell_centroid,
        ):
            point_on_edge, edge_measure, _, right_of_edge = (
                edge_geometry.queryPointAndDistance(point_on_intersection, True)
            )
            snap_distance_m = _geodesic_distance_m(
                point_on_intersection,
                point_on_edge,
            )
            if snap_distance_m > snap_tolerance_m:
                logger.debug(
                    "Skipping representative for H3 %s on source %s OID %s: snap %.6f m exceeds %.6f m",
                    h3_id_hex,
                    edge_evidence.source_id,
                    edge_evidence.source_oid,
                    snap_distance_m,
                    snap_tolerance_m,
                )
                continue
            candidates.append(
                RepresentativeCandidate(
                    h3_id_hex=h3_id_hex,
                    point_geometry=point_on_edge,
                    source_id=edge_evidence.source_id,
                    source_oid=edge_evidence.source_oid,
                    pos_along=float(edge_measure),
                    centroid_distance_m=_geodesic_distance_m(
                        cell_centroid,
                        point_on_edge,
                    ),
                    snap_distance_m=float(snap_distance_m),
                    right_of_edge=bool(right_of_edge),
                )
            )

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.centroid_distance_m,
            candidate.source_id,
            candidate.source_oid,
            candidate.pos_along,
        ),
    )


def _nearest_intersection_points(
    intersection_geometry: arcpy.Geometry,
    cell_centroid: arcpy.Geometry,
) -> list[arcpy.Geometry]:
    """Return the nearest point(s) on a point/multipoint/polyline intersection."""
    geometry_type = intersection_geometry.type.casefold()
    if geometry_type == "point":
        return [intersection_geometry]
    if geometry_type == "multipoint":
        points: list[arcpy.Geometry] = []
        for part_index in range(intersection_geometry.partCount):
            part = intersection_geometry.getPart(part_index)
            for point in part:
                points.append(
                    arcpy.PointGeometry(point, intersection_geometry.spatialReference)
                )
        if not points:
            return []
        point_distances = [
            _geodesic_distance_m(cell_centroid, point) for point in points
        ]
        minimum_distance = min(point_distances)
        return [
            point
            for point, distance in zip(points, point_distances)
            if abs(distance - minimum_distance) <= 1e-6
        ]
    if geometry_type in {"polyline", "line"}:
        nearest_point, _, _, _ = intersection_geometry.queryPointAndDistance(
            cell_centroid.firstPoint,
            False,
        )
        return [nearest_point]
    raise ValueError(
        f"Unsupported edge/cell intersection geometry: {intersection_geometry.type}"
    )


def _validate_matching_reference(first_geometry: Any, second_geometry: Any) -> None:
    """Ensure both geometries have the same declared CRS."""
    second_reference = second_geometry.spatialReference
    if second_reference is None or second_reference.name == "Unknown":
        raise ValueError(
            "Representative input geometry has an unknown spatial reference"
        )
    if first_geometry.spatialReference != second_reference:
        raise ValueError(
            "Representative input geometries must use the same spatial reference"
        )


def _geodesic_distance_m(first_point: Any, second_point: Any) -> float:
    """Measure distance between point geometries geodesically in meters."""
    return float(first_point.angleAndDistanceTo(second_point, "GEODESIC")[1])
