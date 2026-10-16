"""ArcPy export of a completed eligibility run as an H3 hexagon review feature class.

The review feature class is an optional, builder-local review aid. It is not part of the shared
data contract and is never published, versioned, or fingerprinted.
"""

import os
from pathlib import Path

import arcpy

from h3_route_data_builder.eligibility.review import (
    expected_review_cell_count,
    iter_review_cells,
)
from h3_route_data_builder.network.geometry import WGS84_CRS_NAME
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

REVIEW_H3_INDEX_FIELD_LENGTH = 20
"""Text length of the ``h3_index`` review field; fits any unsigned 64-bit decimal integer."""

REVIEW_STATUS_FIELD_LENGTH = 32
"""Text length of the ``eligibility_status`` review field."""


def export_eligibility_review_feature_class(
    run_directory: str | os.PathLike[str],
    output_feature_class: str | os.PathLike[str],
) -> int:
    """Write a WGS 84 hexagon feature class of eligibility results for interactive review.

    Each row holds the stored GeoParquet ``cell_geometry`` polygon, ``h3_index`` (Text 20, the
    exact decimal integer H3 index, equal to ``str(h3_id)``), and ``eligibility_status``
    (Text 32). Rows are inserted in ascending ``h3_id`` order. Geometry is copied, not
    recomputed or reprojected.

    !!! note
        ArcGIS Big Integer fields are limited to 53 bits, and every H3 index needs about 60
        bits. ``h3_index`` is therefore stored as text so the integer is exact.

    !!! warning
        The output workspace must be a file, mobile, or enterprise geodatabase.

    ```python
    count = export_eligibility_review_feature_class(
        "output/eligibility-run-abc123",
        "review.gdb/eligibility_review",
    )
    ```

    Args:
        run_directory: Completed eligibility run directory containing ``run-manifest.json``.
        output_feature_class: Geodatabase feature class path to create.

    Returns:
        int: Number of features written.

    Raises:
        ValueError: If the run is not complete or fails validation, the target already exists
            and overwrite is disabled, or the written count differs from the manifest count.
        Exception: Any ArcPy failure is re-raised after the partial output is deleted.
    """
    output_path = Path(output_feature_class)
    output = str(output_path)
    logger.info("Starting eligibility review export from %s", run_directory)
    logger.info("Review feature class target: %s", output)

    if arcpy.Exists(output) and not arcpy.env.overwriteOutput:
        message = f"Review feature class already exists and overwrite is disabled: {output}"
        logger.error(message)
        raise ValueError(message)

    expected_count = expected_review_cell_count(run_directory)
    cells = iter_review_cells(run_directory)
    spatial_reference = arcpy.SpatialReference(WGS84_CRS_NAME)
    written_count = 0
    try:
        arcpy.management.CreateFeatureclass(
            out_path=str(output_path.parent),
            out_name=output_path.name,
            geometry_type="POLYGON",
            spatial_reference=spatial_reference,
        )
        arcpy.management.AddField(
            in_table=output,
            field_name="h3_index",
            field_type="TEXT",
            field_length=REVIEW_H3_INDEX_FIELD_LENGTH,
            field_is_nullable="NON_NULLABLE",
        )
        arcpy.management.AddField(
            in_table=output,
            field_name="eligibility_status",
            field_type="TEXT",
            field_length=REVIEW_STATUS_FIELD_LENGTH,
            field_is_nullable="NON_NULLABLE",
        )
        logger.debug("Created review feature class schema at %s", output)
        with arcpy.da.InsertCursor(output, ["SHAPE@", "h3_index", "eligibility_status"]) as cursor:
            for cell in cells:
                geometry = arcpy.FromWKB(cell.cell_geometry_wkb, spatial_reference)
                cursor.insertRow((geometry, str(cell.h3_id), cell.eligibility_status))
                written_count += 1
        if written_count != expected_count:
            raise ValueError(
                f"Review feature class count {written_count} does not match manifest "
                f"cell_result_count {expected_count}"
            )
    except Exception as exc:
        message = f"Eligibility review export to '{output}' failed: {exc}"
        logger.error(message)
        _delete_partial_output(output)
        raise

    if written_count == 0:
        logger.warning("Review feature class %s was written with 0 features", output)
    logger.info("Wrote %s features to review feature class %s", written_count, output)
    logger.info("Completed eligibility review export to %s", output)
    return written_count


def _delete_partial_output(output: str) -> None:
    """Delete a partial review output without masking the original failure."""
    try:
        if arcpy.Exists(output):
            arcpy.management.Delete(in_data=output)
            logger.info("Deleted partial review feature class %s", output)
    except Exception as exc:
        logger.error("Could not delete partial review feature class '%s': %s", output, exc)
