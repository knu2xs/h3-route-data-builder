"""ArcPy geometry validation, projection, clipping, and topology operations."""

from dataclasses import dataclass
import uuid

import arcpy

from h3_route_data_builder.eligibility.cells import h3_candidate_ids, h3_cell_boundary
from h3_route_data_builder.utils import get_logger
from h3_route_data_builder.eligibility.models import CellEligibilityResult

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


@dataclass(frozen=True)
class GeometryIntersection:
    """Point and line components of a topological geometry intersection."""

    points: arcpy.Geometry | None
    lines: arcpy.Geometry | None


def validate_aoi_geometry(
    aoi_geometry: arcpy.Geometry | None,
) -> arcpy.SpatialReference:
    """Validate a polygon AOI without repairing or assigning its spatial reference.

    Args:
        aoi_geometry: AOI geometry supplied by an ArcPy feature class or layer.

    Returns:
        The declared source spatial reference.

    Raises:
        ValueError: If the AOI is empty, not polygonal, has an unknown spatial reference,
            or contains geometry errors.
        RuntimeError: If ArcPy cannot complete geometry validation.
    """
    if aoi_geometry is None or aoi_geometry.pointCount == 0:
        raise ValueError("AOI geometry must be non-empty")
    if aoi_geometry.type.casefold() != "polygon":
        raise ValueError("AOI geometry must be polygonal")

    source_reference = aoi_geometry.spatialReference
    if source_reference is None or source_reference.name == "Unknown":
        raise ValueError("AOI geometry has an unknown spatial reference")

    token = uuid.uuid4().hex
    input_features = f"memory/aoi_validation_{token}"
    problem_table = f"memory/aoi_validation_errors_{token}"
    try:
        arcpy.management.CopyFeatures([aoi_geometry], input_features)
        arcpy.management.CheckGeometry(
            in_features=input_features,
            out_table=problem_table,
            validation_method="OGC",
        )
        problem_count = int(arcpy.management.GetCount(problem_table)[0])
        if problem_count:
            raise ValueError(
                f"AOI geometry is invalid; ArcPy CheckGeometry reported {problem_count} issue(s)"
            )
    except ValueError:
        raise
    except arcpy.ExecuteError as exc:
        message = f"Could not validate AOI geometry: {arcpy.GetMessages(2)}"
        logger.error(message)
        raise RuntimeError(message) from exc
    finally:
        for dataset in (problem_table, input_features):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)

    return source_reference


def project_geometry(
    geometry: arcpy.Geometry,
    target_spatial_reference: arcpy.SpatialReference,
    datum_transformation: str | None = None,
) -> arcpy.Geometry:
    """Project geometry explicitly into a configured projected spatial reference.

    Args:
        geometry: Input ArcPy geometry with a declared spatial reference.
        target_spatial_reference: Configured projected spatial reference.
        datum_transformation: Required ArcGIS transformation name when source and target
            geodetic datums differ.

    Returns:
        A new geometry projected to the target spatial reference.

    Raises:
        ValueError: If either reference is unknown, target is not projected, or a required
            datum transformation is not supplied.
        RuntimeError: If ArcPy projection fails.
    """
    if geometry is None or geometry.pointCount == 0:
        raise ValueError("Geometry must be non-empty before projection")
    source_spatial_reference = geometry.spatialReference
    if source_spatial_reference is None or source_spatial_reference.name == "Unknown":
        raise ValueError("Input geometry has an unknown spatial reference")
    if target_spatial_reference is None or target_spatial_reference.name == "Unknown":
        raise ValueError("Target spatial reference must be known")
    if target_spatial_reference.type != "Projected":
        raise ValueError("Target spatial reference must be projected")

    source_geodetic_name = source_spatial_reference.GCS.name
    target_geodetic_name = target_spatial_reference.GCS.name
    if source_geodetic_name != target_geodetic_name and not datum_transformation:
        raise ValueError(
            "A datum transformation is required between the source and target references"
        )

    try:
        projected = geometry.projectAs(
            target_spatial_reference, datum_transformation or ""
        )
    except arcpy.ExecuteError as exc:
        message = f"Could not project geometry from '{source_spatial_reference.name}' to '{target_spatial_reference.name}': {arcpy.GetMessages(2)}"
        logger.error(message)
        raise RuntimeError(message) from exc

    logger.info(
        "Projected geometry from %s to %s%s",
        source_spatial_reference.name,
        target_spatial_reference.name,
        f" using {datum_transformation}" if datum_transformation else "",
    )
    return projected


def candidate_h3_cells_for_aoi(
    aoi_geometry: arcpy.Geometry,
    resolution: int,
    datum_transformation: str | None = None,
) -> list[str]:
    """Project a valid AOI to H3's geographic coordinates and return candidate cell IDs.

    This result is a conservative cover only. Eligible cells still require an exact ArcPy
    intersection with an eligible in-AOI network edge.

    Args:
        aoi_geometry: Valid AOI polygon with a declared ArcPy spatial reference.
        resolution: Configured H3 resolution from 0 through 15.
        datum_transformation: ArcGIS transformation name when the AOI datum differs from WGS 84.

    Returns:
        Canonical lowercase hexadecimal candidate H3 IDs in deterministic order.

    Raises:
        ValueError: If the AOI, resolution, or required datum transformation is invalid.
        RuntimeError: If ArcPy cannot project the AOI to H3 geographic coordinates.
    """
    validate_aoi_geometry(aoi_geometry)
    h3_spatial_reference = arcpy.SpatialReference("GCS_WGS_1984")
    source_reference = aoi_geometry.spatialReference
    if (
        source_reference.GCS.name != h3_spatial_reference.GCS.name
        and not datum_transformation
    ):
        raise ValueError(
            "A datum transformation is required to project the AOI to H3 coordinates"
        )
    try:
        aoi_in_h3_coordinates = aoi_geometry.projectAs(
            h3_spatial_reference,
            datum_transformation or "",
        )
    except arcpy.ExecuteError as exc:
        message = f"Could not project AOI to H3 geographic coordinates: {arcpy.GetMessages(2)}"
        logger.error(message)
        raise RuntimeError(message) from exc

    geojson_geometry = getattr(aoi_in_h3_coordinates, "__geo_interface__", None)
    if geojson_geometry is None:
        raise ValueError("ArcPy AOI geometry does not expose a GeoJSON interface")
    candidates = h3_candidate_ids(geojson_geometry, resolution)
    logger.info(
        "Generated %s H3 candidates at resolution %s", len(candidates), resolution
    )
    return candidates


def h3_cell_polygon(
    cell_id: str,
    working_spatial_reference: arcpy.SpatialReference,
    datum_transformation: str | None = None,
) -> arcpy.Geometry:
    """Construct and project a canonical H3 cell polygon with ArcPy.

    Args:
        cell_id: Canonical H3 cell ID.
        working_spatial_reference: Configured projected CRS for geometry operations.
        datum_transformation: Required ArcGIS transformation when datums differ.

    Returns:
        H3 cell polygon projected to the configured working reference.

    Raises:
        ValueError: If the cell ID or target CRS is invalid.
        RuntimeError: If ArcPy cannot construct or project the geometry.
    """
    boundary = h3_cell_boundary(cell_id)
    if len(boundary) < 3:
        raise ValueError(f"H3 cell {cell_id!r} has fewer than three boundary vertices")

    h3_spatial_reference = arcpy.SpatialReference("GCS_WGS_1984")
    closed_boundary = list(boundary)
    if closed_boundary[0] != closed_boundary[-1]:
        closed_boundary.append(closed_boundary[0])
    points = arcpy.Array(
        [arcpy.Point(longitude, latitude) for longitude, latitude in closed_boundary]
    )
    try:
        polygon = arcpy.Polygon(points, h3_spatial_reference)
    except arcpy.ExecuteError as exc:
        message = f"Could not construct ArcPy polygon for H3 cell {cell_id!r}: {arcpy.GetMessages(2)}"
        logger.error(message)
        raise RuntimeError(message) from exc
    return project_geometry(polygon, working_spatial_reference, datum_transformation)


def cell_result_geometries_wkb(
    results: list[CellEligibilityResult],
    storage_spatial_reference: arcpy.SpatialReference,
    datum_transformation: str | None = None,
) -> dict[str, tuple[bytes, bytes, bytes | None]]:
    """Project cell output geometries to storage CRS and encode them as WKB.

    Args:
        results: Validated cell results with ArcPy cell, centroid, and representative geometry.
        storage_spatial_reference: Explicit configured CRS for the serialized GeoParquet output.
        datum_transformation: ArcGIS transformation to apply when source and storage datums differ.

    Returns:
        H3 ID to cell WKB, centroid WKB, and optional representative WKB mapping.

    Raises:
        ValueError: If required geometries or spatial references are missing or unknown.
        RuntimeError: If ArcPy cannot project an output geometry.
    """
    if storage_spatial_reference is None or storage_spatial_reference.name == "Unknown":
        raise ValueError("storage_spatial_reference must be known")

    serialized: dict[str, tuple[bytes, bytes, bytes | None]] = {}
    for result in results:
        if result.cell_geometry is None or result.centroid_geometry is None:
            raise ValueError(
                f"Cell and centroid geometry are required for H3 cell {result.h3_id_hex}"
            )
        centroid_geometry = result.centroid_geometry
        if not hasattr(centroid_geometry, "spatialReference"):
            centroid_geometry = arcpy.PointGeometry(
                centroid_geometry,
                result.cell_geometry.spatialReference,
            )
        cell_storage = _project_for_storage(
            result.cell_geometry,
            storage_spatial_reference,
            datum_transformation,
        )
        centroid_storage = _project_for_storage(
            centroid_geometry,
            storage_spatial_reference,
            datum_transformation,
        )
        representative_wkb: bytes | None = None
        if result.representative is not None:
            working_reference = result.cell_geometry.spatialReference
            point_geometry = arcpy.PointGeometry(
                arcpy.Point(result.representative.x, result.representative.y),
                working_reference,
            )
            representative_storage = _project_for_storage(
                point_geometry,
                storage_spatial_reference,
                datum_transformation,
            )
            representative_wkb = bytes(representative_storage.WKB)
        serialized[result.h3_id_hex] = (
            bytes(cell_storage.WKB),
            bytes(centroid_storage.WKB),
            representative_wkb,
        )
    return serialized


def _project_for_storage(
    geometry: arcpy.Geometry,
    storage_spatial_reference: arcpy.SpatialReference,
    datum_transformation: str | None,
) -> arcpy.Geometry:
    """Project one geometry to the declared storage CRS, including geographic CRSs."""
    source_reference = geometry.spatialReference
    if source_reference is None or source_reference.name == "Unknown":
        raise ValueError("Output geometry has an unknown spatial reference")
    if (
        source_reference.GCS.name != storage_spatial_reference.GCS.name
        and not datum_transformation
    ):
        raise ValueError(
            "A datum transformation is required for output storage geometry"
        )
    try:
        return geometry.projectAs(storage_spatial_reference, datum_transformation or "")
    except arcpy.ExecuteError as exc:
        message = (
            f"Could not project output geometry to '{storage_spatial_reference.name}': "
            f"{arcpy.GetMessages(2)}"
        )
        logger.error(message)
        raise RuntimeError(message) from exc


def geometry_intersection(
    first_geometry: arcpy.Geometry,
    second_geometry: arcpy.Geometry,
) -> GeometryIntersection:
    """Return point and line components of the inclusive topological intersection.

    Args:
        first_geometry: First geometry in the configured projected CRS.
        second_geometry: Second geometry in the same projected CRS.

    Returns:
        Zero-dimensional and one-dimensional intersection geometries, or ``None`` for
        a dimension with no shared geometry.

    Raises:
        ValueError: If either geometry is empty, has unknown CRS, or the references differ.
    """
    _validate_matching_projected_references(first_geometry, second_geometry)
    if first_geometry.disjoint(second_geometry):
        return GeometryIntersection(points=None, lines=None)

    point_intersection = first_geometry.intersect(second_geometry, 1)
    line_intersection = first_geometry.intersect(second_geometry, 2)
    return GeometryIntersection(
        points=point_intersection if point_intersection.pointCount else None,
        lines=line_intersection if line_intersection.pointCount else None,
    )


def intersects_inclusive(
    first_geometry: arcpy.Geometry,
    second_geometry: arcpy.Geometry,
) -> bool:
    """Return whether two projected geometries share any point, line, or area.

    Args:
        first_geometry: First geometry in the configured projected CRS.
        second_geometry: Second geometry in the same projected CRS.

    Returns:
        True if the geometries intersect at any topological dimension.
    """
    if first_geometry.disjoint(second_geometry):
        return False
    intersection = geometry_intersection(first_geometry, second_geometry)
    return intersection.points is not None or intersection.lines is not None


def clip_edge_to_aoi(
    edge_geometry: arcpy.Geometry,
    aoi_geometry: arcpy.Geometry,
) -> GeometryIntersection:
    """Clip edge geometry to the AOI while preserving boundary point contacts.

    Args:
        edge_geometry: Polyline edge in the working projected CRS.
        aoi_geometry: Valid polygon AOI in the same working projected CRS.

    Returns:
        Point and line components of the edge/AOI intersection.
    """
    if edge_geometry.type.casefold() not in {"polyline", "line"}:
        raise ValueError("Transportation edge geometry must be a polyline")
    if aoi_geometry.type.casefold() != "polygon":
        raise ValueError("AOI geometry must be polygonal")
    return geometry_intersection(edge_geometry, aoi_geometry)


def _validate_matching_projected_references(
    first_geometry: arcpy.Geometry,
    second_geometry: arcpy.Geometry,
) -> None:
    """Validate non-empty geometries share a known projected spatial reference."""
    if first_geometry is None or first_geometry.pointCount == 0:
        raise ValueError("First geometry must be non-empty")
    if second_geometry is None or second_geometry.pointCount == 0:
        raise ValueError("Second geometry must be non-empty")
    first_reference = first_geometry.spatialReference
    second_reference = second_geometry.spatialReference
    if first_reference is None or first_reference.name == "Unknown":
        raise ValueError("First geometry has an unknown spatial reference")
    if second_reference is None or second_reference.name == "Unknown":
        raise ValueError("Second geometry has an unknown spatial reference")
    if first_reference.type != "Projected" or second_reference.type != "Projected":
        raise ValueError("Geometry operations require projected spatial references")
    if first_reference != second_reference:
        raise ValueError(
            "Geometry inputs must use the same projected spatial reference"
        )
