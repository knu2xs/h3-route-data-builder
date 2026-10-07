"""Batched Network Analyst location calculation and representative validation."""

from collections.abc import Mapping
import uuid

import arcpy

from h3_route_data_builder.eligibility.models import NetworkLocation
from h3_route_data_builder.network.representatives import RepresentativeCandidate
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

_LOCATION_FIELDS = [
    "SourceID",
    "SourceOID",
    "PosAlong",
    "SideOfEdge",
    "DistanceToNetworkInMeters",
]


def locate_representative_candidates(
    candidates: list[RepresentativeCandidate],
    network_dataset_path: str,
    travel_mode: str,
    snap_tolerance_m: float,
) -> NetworkLocation | None:
    """Locate a single cell's candidates and return its first matching network location."""
    if not candidates:
        return None
    return locate_representative_candidates_by_cell(
        {candidates[0].h3_id_hex: candidates},
        network_dataset_path,
        travel_mode,
        snap_tolerance_m,
    )[candidates[0].h3_id_hex]


def locate_representative_candidates_by_cell(
    candidates_by_cell: Mapping[str, list[RepresentativeCandidate]],
    network_dataset_path: str,
    travel_mode: str,
    snap_tolerance_m: float,
) -> dict[str, NetworkLocation | None]:
    """Locate ranked representative candidates for many H3 cells in one ArcPy call.

    Candidate points are written to one temporary memory feature class. The input network
    dataset is used read-only by Calculate Locations. Candidate order and H3 identity fields
    are preserved so the first valid location per cell is chosen deterministically.

    Args:
        candidates_by_cell: H3 ID to centroid-distance/source/OID/measure-ranked candidates.
        network_dataset_path: ArcPy network dataset path.
        travel_mode: Travel mode whose restrictions are used while locating.
        snap_tolerance_m: Maximum accepted location distance in meters.

    Returns:
        H3 ID to validated Network Analyst location, or None when no candidate for that cell
        matches its intended source/OID and tolerance.

    Raises:
        ValueError: If required inputs or candidate geometries are invalid.
        RuntimeError: If ArcPy cannot calculate locations or returns an incomplete schema.
    """
    ordered_candidates: list[RepresentativeCandidate] = []
    result_by_cell: dict[str, NetworkLocation | None] = {
        cell_id: None for cell_id in sorted(candidates_by_cell)
    }
    for cell_id in sorted(candidates_by_cell):
        cell_candidates = sorted(
            candidates_by_cell[cell_id],
            key=lambda candidate: (
                candidate.centroid_distance_m,
                candidate.source_id,
                candidate.source_oid,
                candidate.pos_along,
            ),
        )
        if any(candidate.h3_id_hex != cell_id for candidate in cell_candidates):
            raise ValueError(f"Candidate H3 ID does not match mapping key {cell_id}")
        ordered_candidates.extend(cell_candidates)

    if not ordered_candidates:
        return result_by_cell
    if not network_dataset_path or not arcpy.Exists(network_dataset_path):
        raise ValueError(
            f"ArcPy cannot resolve network dataset: {network_dataset_path}"
        )
    if not travel_mode:
        raise ValueError("travel_mode must be non-empty")
    if snap_tolerance_m < 0:
        raise ValueError("snap_tolerance_m must be non-negative")

    spatial_reference = ordered_candidates[0].point_geometry.spatialReference
    if spatial_reference is None or spatial_reference.name == "Unknown":
        raise ValueError("Representative points must have a known spatial reference")
    if spatial_reference.type != "Projected":
        raise ValueError("Representative points must use a projected spatial reference")
    if any(
        candidate.point_geometry.spatialReference != spatial_reference
        for candidate in ordered_candidates
    ):
        raise ValueError("All representative candidates must use the same working CRS")

    feature_class_name = f"representatives_{uuid.uuid4().hex}"
    feature_class = f"memory/{feature_class_name}"
    arcpy.management.CreateFeatureclass(
        out_path="memory",
        out_name=feature_class_name,
        geometry_type="POINT",
        spatial_reference=spatial_reference,
    )
    arcpy.management.AddField(feature_class, "candidate_index", "LONG")
    arcpy.management.AddField(feature_class, "h3_id_hex", "TEXT", field_length=16)
    try:
        with arcpy.da.InsertCursor(
            feature_class,
            ["candidate_index", "h3_id_hex", "SHAPE@"],
        ) as cursor:
            for candidate_index, candidate in enumerate(ordered_candidates):
                cursor.insertRow(
                    [candidate_index, candidate.h3_id_hex, candidate.point_geometry]
                )

        try:
            arcpy.na.CalculateLocations(
                in_point_features=feature_class,
                in_network_dataset=network_dataset_path,
                search_tolerance=f"{snap_tolerance_m} Meters",
                travel_mode=travel_mode,
            )
        except arcpy.ExecuteError as exc:
            message = (
                f"Calculate Locations failed for network '{network_dataset_path}' "
                f"and travel mode '{travel_mode}': {arcpy.GetMessages(2)}"
            )
            logger.error(message)
            raise RuntimeError(message) from exc

        fields = {field.name for field in arcpy.ListFields(feature_class)}
        missing_fields = [field for field in _LOCATION_FIELDS if field not in fields]
        if missing_fields:
            raise RuntimeError(
                "Calculate Locations did not produce required fields: "
                + ", ".join(missing_fields)
            )

        located_by_index: dict[int, tuple[object, ...]] = {}
        with arcpy.da.SearchCursor(
            feature_class,
            ["candidate_index", "h3_id_hex", *_LOCATION_FIELDS],
        ) as cursor:
            for row in cursor:
                candidate_index = int(row[0])
                if row[1] != ordered_candidates[candidate_index].h3_id_hex:
                    raise RuntimeError(
                        "Calculate Locations changed candidate H3 identity"
                    )
                located_by_index[candidate_index] = tuple(row[2:])

        for candidate_index, candidate in enumerate(ordered_candidates):
            if result_by_cell[candidate.h3_id_hex] is not None:
                continue
            row = located_by_index.get(candidate_index)
            if row is None:
                continue
            source_id, source_oid, pos_along, side_of_edge, distance_m = row
            if any(value is None for value in row):
                logger.warning(
                    "Candidate %s for H3 %s was not located",
                    candidate_index,
                    candidate.h3_id_hex,
                )
                continue
            if (
                int(source_id) != candidate.source_id
                or int(source_oid) != candidate.source_oid
            ):
                logger.warning(
                    "Candidate %s for H3 %s located on source %s OID %s instead of source %s OID %s",
                    candidate_index,
                    candidate.h3_id_hex,
                    source_id,
                    source_oid,
                    candidate.source_id,
                    candidate.source_oid,
                )
                continue
            if not 0.0 <= float(pos_along) <= 1.0:
                logger.warning(
                    "Candidate %s for H3 %s has invalid PosAlong %s",
                    candidate_index,
                    candidate.h3_id_hex,
                    pos_along,
                )
                continue
            if float(distance_m) > snap_tolerance_m:
                logger.warning(
                    "Candidate %s for H3 %s snapped %.6f m beyond tolerance %.6f m",
                    candidate_index,
                    candidate.h3_id_hex,
                    distance_m,
                    snap_tolerance_m,
                )
                continue

            point = candidate.point_geometry.centroid
            result_by_cell[candidate.h3_id_hex] = NetworkLocation(
                x=float(point.X),
                y=float(point.Y),
                source_id=int(source_id),
                source_oid=int(source_oid),
                pos_along=float(pos_along),
                side_of_edge=int(side_of_edge),
                snap_distance_m=float(distance_m),
            )
    except arcpy.ExecuteError as exc:
        message = f"Network location validation failed: {arcpy.GetMessages(2)}"
        logger.error(message)
        raise RuntimeError(message) from exc
    finally:
        if arcpy.Exists(feature_class):
            arcpy.management.Delete(feature_class)

    located_count = sum(location is not None for location in result_by_cell.values())
    logger.info(
        "Validated Network Analyst locations for %s of %s H3 candidate cells",
        located_count,
        len(result_by_cell),
    )
    return result_by_cell
