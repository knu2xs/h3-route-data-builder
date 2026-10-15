"""Portable H3 cell identity helpers."""

from collections.abc import Iterable, Mapping
from typing import Any

from h3.api import basic_int as h3
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


def canonical_h3_ids(cell_ids: Iterable[int]) -> list[int]:
    """Validate, deduplicate, and numerically sort H3 cell IDs.

    Args:
        cell_ids: Exact integer H3 cell IDs.

    Returns:
        Unique integer cell IDs sorted by numeric value.

    Raises:
        ValueError: If any supplied value is not a valid H3 cell ID.
    """
    canonical: set[int] = set()
    for cell_id in cell_ids:
        if type(cell_id) is not int or not 0 <= cell_id < 2**64 or not h3.is_valid_cell(cell_id):
            message = f"Invalid H3 cell ID: {cell_id!r}"
            logger.error(message)
            raise ValueError(message)
        canonical.add(cell_id)
    ordered_ids = sorted(canonical)
    if len(ordered_ids) > 1:
        logger.debug("Canonicalized H3 input into %s unique cell IDs", len(ordered_ids))
    return ordered_ids


def h3_candidate_ids(aoi_geojson: Mapping[str, Any], resolution: int) -> list[int]:
    """Return a deterministic conservative H3 cover for a GeoJSON-like AOI.

    The returned IDs are only candidates. Spatial eligibility must be established by the
    ArcPy geometry adapter's exact edge/cell intersection test.

    Args:
        aoi_geojson: GeoJSON-like polygon or multipolygon in longitude/latitude order.
        resolution: H3 resolution from 0 through 15.

    Returns:
        Integer candidate IDs sorted by numeric value.

    Raises:
        ValueError: If resolution is out of range or the AOI cannot be converted to H3 shape.
    """
    if type(resolution) is not int or not 0 <= resolution <= 15:
        message = "H3 resolution must be an integer between 0 and 15"
        logger.error(message)
        raise ValueError(message)
    try:
        h3_shape = h3.geo_to_h3shape(aoi_geojson)
        candidate_ids = h3.h3shape_to_cells_experimental(
            h3_shape,
            resolution,
            contain="bbox_overlap",
        )
    except Exception as exc:
        message = f"Could not generate H3 candidates for AOI: {exc}"
        logger.error(message)
        raise ValueError(message) from exc
    ordered_candidates = canonical_h3_ids(candidate_ids)
    logger.info(
        "Generated %s H3 candidates at resolution %s",
        len(ordered_candidates),
        resolution,
    )
    return ordered_candidates


def h3_cell_boundary(cell_id: int) -> tuple[tuple[float, float], ...]:
    """Return a canonical H3 boundary as longitude/latitude coordinate pairs.

    Args:
        cell_id: Exact integer H3 cell ID.

    Returns:
        Boundary coordinates in GeoJSON order (longitude, latitude), without a repeated
        closing coordinate.

    Raises:
        ValueError: If the ID is not a valid H3 cell.
    """
    canonical_h3_ids([cell_id])
    return tuple((longitude, latitude) for latitude, longitude in h3.cell_to_boundary(cell_id))
