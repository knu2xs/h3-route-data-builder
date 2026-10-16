"""Portable streaming of validated cells from a completed eligibility run for review export.

This module reads only the run manifest and the GeoParquet parts it lists. It never writes to
the run directory and does not import ArcPy, so it can be tested in any Python environment.
"""

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import pyarrow as pa
from h3.api import basic_int as h3

from .cells import canonical_h3_ids
from .models import RunStatus
from .staging import StagedPart, read_verified_staged_part
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

RUN_MANIFEST_NAME = "run-manifest.json"
"""File name of the eligibility run manifest written by ``run_geometry_eligibility``."""

_REVIEW_COLUMNS = ["h3_id", "resolution", "eligibility_status", "cell_geometry"]


@dataclass(frozen=True)
class ReviewCell:
    """One validated eligibility row selected for the review feature class.

    Args:
        h3_id: Exact integer H3 cell index, identical to GeoParquet ``h3_id``.
        eligibility_status: GeoParquet ``eligibility_status`` value, unchanged.
        cell_geometry_wkb: WGS 84 polygon WKB copied from GeoParquet ``cell_geometry``.
    """

    h3_id: int
    eligibility_status: str
    cell_geometry_wkb: bytes


def expected_review_cell_count(run_directory: str | os.PathLike[str]) -> int:
    """Return the number of cell results recorded by a completed eligibility run.

    ```python
    count = expected_review_cell_count("output/eligibility-run-abc123")
    ```

    Args:
        run_directory: Eligibility run directory containing ``run-manifest.json``.

    Returns:
        int: Manifest ``cell_result_count``.

    Raises:
        ValueError: If the manifest is missing, unreadable, incomplete, or lacks the count.
    """
    manifest = _load_complete_manifest(Path(run_directory))
    return _manifest_int(manifest, "cell_result_count")


def iter_review_cells(run_directory: str | os.PathLike[str]) -> Iterator[ReviewCell]:
    """Yield validated cells from a completed run in strictly ascending ``h3_id`` order.

    The manifest is validated when this function is called; part contents are validated
    while iterating. Partitions are read in manifest ``expected_partition_keys`` order, and at
    most one partition's rows are held in memory at a time. Only manifest-listed parts are
    read, each after checksum and row-count verification.

    ```python
    for cell in iter_review_cells("output/eligibility-run-abc123"):
        print(cell.h3_id, cell.eligibility_status)
    ```

    Args:
        run_directory: Eligibility run directory containing ``run-manifest.json``.

    Returns:
        Iterator[ReviewCell]: Cells in ascending ``h3_id`` order.

    Raises:
        ValueError: If the run is not complete, a part fails verification, an ``h3_id`` is not
            a valid cell at the run resolution, ``h3_id`` order is not strictly ascending, or
            a required value is null or empty.
    """
    run_path = Path(run_directory)
    manifest = _load_complete_manifest(run_path)
    resolution = _manifest_int(manifest.get("policy") or {}, "h3_resolution")
    partition_keys = manifest.get("expected_partition_keys")
    if not isinstance(partition_keys, list):
        _raise_value_error(f"Run manifest in '{run_path}' has no expected_partition_keys list")
    logger.info(
        "Reading review cells from %s across %s partitions at resolution %s",
        run_path,
        len(partition_keys),
        resolution,
    )
    return _generate_review_cells(run_path, manifest, partition_keys, resolution)


def _generate_review_cells(
    run_path: Path,
    manifest: dict[str, Any],
    partition_keys: list[str],
    resolution: int,
) -> Iterator[ReviewCell]:
    """Stream validated cells partition by partition."""
    previous_h3_id: int | None = None
    yielded_count = 0
    for partition_key in partition_keys:
        table = _read_partition(run_path, manifest, partition_key)
        if table is None:
            continue
        for row in table.to_pylist():
            cell = _validated_review_cell(row, resolution, previous_h3_id)
            previous_h3_id = cell.h3_id
            yielded_count += 1
            yield cell
        logger.debug("Yielded review cells through partition %s", partition_key)
    logger.info("Yielded %s review cells from %s", yielded_count, run_path)


def _read_partition(
    run_path: Path, manifest: dict[str, Any], partition_key: str
) -> pa.Table | None:
    """Read and sort every verified manifest-listed part for one partition."""
    entries = [part for part in manifest.get("parts", []) if part["partition_key"] == partition_key]
    tables: list[pa.Table] = []
    for entry in entries:
        staged_part = StagedPart(
            part_key=entry["part_key"],
            path=run_path / entry["path"],
            row_count=int(entry["row_count"]),
            checksum=entry["checksum"],
        )
        try:
            table = read_verified_staged_part(staged_part)
        except ValueError as exc:
            _raise_value_error(f"Part '{staged_part.part_key}' failed verification: {exc}", exc)
        tables.append(table.select(_REVIEW_COLUMNS))
    logger.debug("Partition %s has %s listed parts", partition_key, len(tables))
    if not tables:
        return None
    return pa.concat_tables(tables).sort_by("h3_id")


def _validated_review_cell(
    row: dict[str, Any], resolution: int, previous_h3_id: int | None
) -> ReviewCell:
    """Validate one part row and convert it to a review cell."""
    h3_id = row["h3_id"]
    try:
        canonical_h3_ids([h3_id])
    except ValueError as exc:
        _raise_value_error(f"Invalid H3 cell in review export: {h3_id!r}", exc)
    if h3.get_resolution(h3_id) != resolution or row["resolution"] != resolution:
        _raise_value_error(
            f"H3 cell {h3_id} resolution {h3.get_resolution(h3_id)} does not match run "
            f"resolution {resolution}"
        )
    if previous_h3_id is not None and h3_id <= previous_h3_id:
        _raise_value_error(
            f"H3 cell {h3_id} is not strictly ascending after {previous_h3_id}; "
            "partitions overlap or are out of order"
        )
    status = row["eligibility_status"]
    if not status:
        _raise_value_error(f"H3 cell {h3_id} has an empty eligibility_status")
    geometry = row["cell_geometry"]
    if not geometry:
        _raise_value_error(f"H3 cell {h3_id} has an empty cell_geometry")
    return ReviewCell(h3_id=h3_id, eligibility_status=status, cell_geometry_wkb=bytes(geometry))


def _load_complete_manifest(run_path: Path) -> dict[str, Any]:
    """Load the run manifest and require a complete run."""
    manifest_path = run_path / RUN_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _raise_value_error(f"Cannot read eligibility run manifest '{manifest_path}': {exc}", exc)
    if not isinstance(manifest, dict):
        _raise_value_error(f"Eligibility run manifest '{manifest_path}' is not a JSON object")
    if manifest.get("run_status") != RunStatus.COMPLETE.value:
        _raise_value_error(
            f"Eligibility run in '{run_path}' is not complete "
            f"(run_status={manifest.get('run_status')!r}); review export requires a complete run"
        )
    return manifest


def _manifest_int(mapping: dict[str, Any], key: str) -> int:
    """Return a required non-negative integer value from manifest data."""
    value = mapping.get(key)
    if type(value) is not int or value < 0:
        _raise_value_error(f"Run manifest value '{key}' must be a non-negative integer: {value!r}")
    return value


def _raise_value_error(message: str, cause: Exception | None = None) -> NoReturn:
    """Log and raise a review validation error."""
    logger.error(message)
    raise ValueError(message) from cause
