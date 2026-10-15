"""Bounded GeoParquet table-file writing and integrity metadata."""

import hashlib
import json
import os
from pathlib import Path
from typing import Literal, overload

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from h3_route_data_builder.eligibility.cells import canonical_h3_ids
from h3_route_data_builder.publication.models import (
    CELL_SCHEMA_VERSION,
    FACT_SCHEMA_VERSION,
    PublishedPart,
)
from h3_route_data_builder.publication.schema import geoparquet_metadata, schema_for
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


@overload
def write_table(
    table: pa.Table,
    output_path: str | os.PathLike[str],
    table_name: Literal["solvable_cells"],
    row_group_size: int = 100_000,
    partition_by_origin: Literal[False] = False,
    part_row_limit: int = 500_000,
) -> PublishedPart: ...


@overload
def write_table(
    table: pa.Table,
    output_path: str | os.PathLike[str],
    table_name: Literal["od_facts"],
    row_group_size: int = 100_000,
    partition_by_origin: Literal[True] = True,
    part_row_limit: int = 500_000,
) -> list[PublishedPart]: ...


@overload
def write_table(
    table: pa.Table,
    output_path: str | os.PathLike[str],
    table_name: Literal["od_facts"],
    row_group_size: int = 100_000,
    partition_by_origin: Literal[False] = False,
    part_row_limit: int = 500_000,
) -> PublishedPart: ...


def write_table(
    table: pa.Table,
    output_path: str | os.PathLike[str],
    table_name: str,
    row_group_size: int = 100_000,
    partition_by_origin: bool = False,
    part_row_limit: int = 500_000,
) -> PublishedPart | list[PublishedPart]:
    """Write one immutable logical table, optionally partitioning facts by origin.

    Writes use a sibling temporary file and atomic replacement. This function creates table
    files only; it never exposes a complete dataset or creates `_SUCCESS`.
    """
    if row_group_size <= 0 or part_row_limit <= 0:
        raise ValueError("row_group_size and part_row_limit must be positive")
    expected_schema = schema_for(table_name)
    if (
        not table.schema.remove_metadata().equals(expected_schema.remove_metadata())
        or (table.schema.metadata or {}).get(b"schema_version")
        != expected_schema.metadata[b"schema_version"]
    ):
        raise ValueError(f"{table_name} table does not match its canonical Arrow schema")
    columns = (
        ("h3_id",) if table_name == "solvable_cells" else ("origin_h3_id", "destination_h3_id")
    )
    for column in columns:
        canonical_h3_ids(table.column(column).to_pylist())
    destination = Path(output_path)
    if partition_by_origin:
        if table_name != "od_facts":
            raise ValueError("Only od_facts can be partitioned by origin")
        parts: list[PublishedPart] = []
        origin_rows: dict[int, list[int]] = {}
        for row_index, origin in enumerate(table.column("origin_h3_id").to_pylist()):
            origin_rows.setdefault(origin, []).append(row_index)
        for origin in sorted(origin_rows):
            origin_table = table.take(pa.array(origin_rows[origin], type=pa.int64()))
            for part_index, row_offset in enumerate(
                range(0, origin_table.num_rows, part_row_limit)
            ):
                part_path = (
                    destination / f"origin_h3_id={origin}" / f"part-{part_index:05d}.parquet"
                )
                parts.append(
                    _write_one(
                        origin_table.slice(row_offset, part_row_limit),
                        part_path,
                        table_name,
                        row_group_size,
                        (origin,),
                    )
                )
        return parts
    return _write_one(table, destination, table_name, row_group_size, ())


def _write_one(
    table: pa.Table,
    destination: Path,
    table_name: str,
    row_group_size: int,
    origin_ids: tuple[int, ...],
) -> PublishedPart:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    extents = _geometry_extents(table, table_name)
    metadata = dict(table.schema.metadata or {})
    if table_name == "solvable_cells":
        metadata[b"geo"] = json.dumps(
            geoparquet_metadata(table.schema, extents),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    output_table = table.replace_schema_metadata(metadata)
    try:
        pq.write_table(output_table, temporary, row_group_size=row_group_size)
        checksum = _sha256_file(temporary)
        os.replace(temporary, destination)
    except Exception as exc:
        message = f"Failed to write {table_name} GeoParquet table at {destination}: {exc}"
        logger.error(message)
        if temporary.exists():
            temporary.unlink()
        raise OSError(message) from exc
    extent = _combined_extent(extents.values()) if extents else None
    schema_version = CELL_SCHEMA_VERSION if table_name == "solvable_cells" else FACT_SCHEMA_VERSION
    recorded_origins = origin_ids
    if table_name == "od_facts" and not recorded_origins:
        recorded_origins = tuple(sorted(set(table.column("origin_h3_id").to_pylist())))
    return PublishedPart(
        table_name=table_name,
        path=destination,
        row_count=table.num_rows,
        checksum=checksum,
        schema_version=schema_version,
        extent=extent,
        origin_ids=recorded_origins,
    )


def _geometry_extents(table: pa.Table, table_name: str) -> dict[str, list[float]]:
    if table_name != "solvable_cells" or table.num_rows == 0:
        return {}
    connection = duckdb.connect()
    connection.execute("LOAD spatial")
    connection.register("publication_geometry", table)
    extents: dict[str, list[float]] = {}
    for column_name in (
        "cell_geometry",
        "centroid_geometry",
        "representative_geometry",
    ):
        values = connection.execute(
            f"SELECT ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent) "
            f"FROM (SELECT ST_Extent(ST_GeomFromWKB({column_name})) AS extent "
            "FROM publication_geometry)"
        ).fetchone()
        if values is None or any(value is None for value in values):
            raise ValueError(f"Geometry column {column_name} has no usable extent")
        extents[column_name] = [float(value) for value in values]
    connection.close()
    return extents


def _combined_extent(extents) -> tuple[float, float, float, float]:
    return (
        min(extent[0] for extent in extents),
        min(extent[1] for extent in extents),
        max(extent[2] for extent in extents),
        max(extent[3] for extent in extents),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
