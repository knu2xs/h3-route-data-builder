"""Portable H3 cell identity helpers."""

from collections.abc import Iterable, Mapping
from typing import Any

import h3
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


def canonical_h3_ids(cell_ids: Iterable[str]) -> list[str]:
    """Validate, deduplicate, and numerically sort H3 cell IDs.

    Args:
        cell_ids: H3 cell IDs in hexadecimal form, in any letter case.

    Returns:
        Canonical lowercase hexadecimal IDs sorted by their H3 integer value.

    Raises:
        ValueError: If any supplied value is not a valid H3 cell ID.
    """
    canonical: set[str] = set()
    for cell_id in cell_ids:
        try:
            normalized_id = cell_id.lower()
            integer_id = h3.str_to_int(normalized_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid H3 cell ID: {cell_id!r}") from exc
        if not h3.is_valid_cell(normalized_id):
            raise ValueError(f"Invalid H3 cell ID: {cell_id!r}")
        canonical.add(h3.int_to_str(integer_id))
    ordered_ids = sorted(canonical, key=h3.str_to_int)
    logger.debug("Canonicalized H3 input into %s unique cell IDs", len(ordered_ids))
    return ordered_ids


def h3_candidate_ids(aoi_geojson: Mapping[str, Any], resolution: int) -> list[str]:
    """Return a deterministic conservative H3 cover for a GeoJSON-like AOI.

    The returned IDs are only candidates. Spatial eligibility must be established by the
    ArcPy geometry adapter's exact edge/cell intersection test.

    Args:
        aoi_geojson: GeoJSON-like polygon or multipolygon in longitude/latitude order.
        resolution: H3 resolution from 0 through 15.

    Returns:
        Canonical lowercase hexadecimal candidate IDs, sorted by H3 integer value.

    Raises:
        ValueError: If resolution is out of range or the AOI cannot be converted to H3 shape.
    """
    if resolution < 0 or resolution > 15:
        raise ValueError("H3 resolution must be between 0 and 15")
    try:
        h3_shape = h3.geo_to_h3shape(aoi_geojson)
        candidate_ids = h3.h3shape_to_cells_experimental(
            h3_shape,
            resolution,
            contain="bbox_overlap",
        )
    except Exception as exc:
        raise ValueError(f"Could not generate H3 candidates for AOI: {exc}") from exc
    ordered_candidates = canonical_h3_ids(candidate_ids)
    logger.info(
        "Generated %s H3 candidates at resolution %s",
        len(ordered_candidates),
        resolution,
    )
    return ordered_candidates


def h3_cell_boundary(cell_id: str) -> tuple[tuple[float, float], ...]:
    """Return a canonical H3 boundary as longitude/latitude coordinate pairs.

    Args:
        cell_id: Canonical H3 cell ID in hexadecimal form.

    Returns:
        Boundary coordinates in GeoJSON order (longitude, latitude), without a repeated
        closing coordinate.

    Raises:
        ValueError: If the ID is not a valid H3 cell.
    """
    normalized_id = cell_id.lower()
    try:
        h3.str_to_int(normalized_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid H3 cell ID: {cell_id!r}") from exc
    if not h3.is_valid_cell(normalized_id):
        raise ValueError(f"Invalid H3 cell ID: {cell_id!r}")
    return tuple(
        (longitude, latitude)
        for latitude, longitude in h3.cell_to_boundary(normalized_id)
    )
