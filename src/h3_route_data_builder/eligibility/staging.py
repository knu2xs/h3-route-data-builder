"""Atomic GeoParquet staging for bounded eligibility output parts."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


@dataclass(frozen=True)
class StagedPart:
    """Metadata identifying one successfully staged spatial part."""

    part_key: str
    path: Path
    row_count: int
    checksum: str


def stage_table_batches(
    table: pa.Table,
    output_directory: str | os.PathLike[str],
    part_prefix: str,
    batch_size: int,
    part_row_limit: int,
) -> list[StagedPart]:
    """Write every row in deterministic batches, subdividing oversized parts.

    Args:
        table: GeoParquet-compatible Arrow table for one input partition.
        output_directory: Destination directory for this partition's part files.
        part_prefix: Stable logical prefix for the partition's part keys.
        batch_size: Maximum source rows admitted to a first-level batch.
        part_row_limit: Maximum rows written to one part.

    Returns:
        Staged part metadata in deterministic input-row order.

    Raises:
        ValueError: If configuration is invalid or table metadata is not GeoParquet.
        OSError: If an atomic part write fails.
    """
    if not part_prefix:
        raise ValueError("part_prefix must be non-empty")
    if batch_size <= 0 or part_row_limit <= 0:
        raise ValueError("batch_size and part_row_limit must be positive")
    if b"geo" not in (table.schema.metadata or {}):
        raise ValueError(
            "GeoParquet schema metadata is required for staged spatial parts"
        )

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    staged_parts: list[StagedPart] = []
    for batch_index, row_offset in enumerate(range(0, table.num_rows, batch_size)):
        batch = table.slice(row_offset, batch_size)
        part_key = f"{part_prefix}-{batch_index:06d}"
        staged_parts.extend(
            _stage_bounded_batch(batch, output_path, part_key, part_row_limit)
        )
    return staged_parts


def _stage_bounded_batch(
    table: pa.Table,
    output_directory: Path,
    part_key: str,
    part_row_limit: int,
) -> list[StagedPart]:
    """Recursively split an oversized table slice and stage its leaves."""
    if table.num_rows <= part_row_limit:
        output_path = output_directory / f"{part_key}.parquet"
        return [write_staged_part(table, output_path, part_key, part_row_limit)]

    split_index = part_row_limit
    logger.info(
        "Subdividing oversized batch %s with %s rows at index %s",
        part_key,
        table.num_rows,
        split_index,
    )
    left_parts = _stage_bounded_batch(
        table.slice(0, split_index),
        output_directory,
        f"{part_key}-0",
        part_row_limit,
    )
    right_parts = _stage_bounded_batch(
        table.slice(split_index),
        output_directory,
        f"{part_key}-1",
        part_row_limit,
    )
    return [*left_parts, *right_parts]


def read_verified_staged_part(staged_part: StagedPart) -> pa.Table:
    """Read one part after verifying its stored checksum and row count.

    Args:
        staged_part: Metadata recorded when the part was written.

    Returns:
        The verified Arrow table.

    Raises:
        ValueError: If the part is absent, its checksum differs, or row count changed.
    """
    if not staged_part.path.is_file():
        raise ValueError(f"Staged part is missing: {staged_part.path}")
    actual_checksum = _sha256_file(staged_part.path)
    if actual_checksum != staged_part.checksum:
        raise ValueError(f"Staged part checksum mismatch: {staged_part.part_key}")
    table = pq.read_table(staged_part.path)
    if table.num_rows != staged_part.row_count:
        raise ValueError(
            f"Staged part row count mismatch for {staged_part.part_key}: "
            f"expected {staged_part.row_count}, found {table.num_rows}"
        )
    return table


def write_staged_part(
    table: pa.Table,
    output_path: str | os.PathLike[str],
    part_key: str,
    row_limit: int,
) -> StagedPart:
    """Atomically write a GeoParquet table under its per-part row limit.

    The caller supplies the GeoParquet schema metadata and deterministic part key.
    A failed write leaves the previous destination untouched and removes its temporary file.

    Args:
        table: Arrow table containing the staged eligibility rows.
        output_path: Destination part path on the staging filesystem.
        part_key: Stable logical identity for this batch.
        row_limit: Maximum rows allowed in this part.

    Returns:
        Part key, resolved output path, row count, and SHA-256 checksum.

    Raises:
        ValueError: If the key/limit is invalid, row limit is exceeded, or GeoParquet metadata
            is missing.
        OSError: If the part cannot be written or atomically replaced.
    """
    if not part_key:
        raise ValueError("part_key must be non-empty")
    if row_limit <= 0:
        raise ValueError("row_limit must be positive")
    if table.num_rows > row_limit:
        raise ValueError(
            f"Part has {table.num_rows} rows; configured limit is {row_limit}"
        )
    if b"geo" not in (table.schema.metadata or {}):
        raise ValueError(
            "GeoParquet schema metadata is required for staged spatial parts"
        )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{part_key}.tmp")
    try:
        pq.write_table(table, temporary)
        checksum = _sha256_file(temporary)
        os.replace(temporary, destination)
    except Exception as exc:
        message = (
            f"Failed to stage eligibility part '{part_key}' at '{destination}': {exc}"
        )
        logger.error(message)
        if temporary.exists():
            temporary.unlink()
        raise OSError(message) from exc

    logger.info(
        "Staged eligibility part %s with %s rows at %s",
        part_key,
        table.num_rows,
        destination,
    )
    return StagedPart(
        part_key=part_key,
        path=destination,
        row_count=table.num_rows,
        checksum=checksum,
    )


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
