"""GeoParquet writer and independent-reader interoperability tests."""

import json

import duckdb
import pyarrow.parquet as pq

from h3_route_data_builder.publication.write import write_table
from testing.publication_fixtures import make_publication_tables


def test_writer_emits_geoparquet_110_and_tables_read_in_pyarrow_and_duckdb(
    temp_dir,
) -> None:
    dimension, facts = make_publication_tables()
    cell_path = temp_dir / "cells.parquet"
    fact_path = temp_dir / "facts.parquet"

    cell_part = write_table(dimension, cell_path, table_name="solvable_cells")
    fact_part = write_table(facts, fact_path, table_name="od_facts")

    metadata = json.loads(pq.ParquetFile(cell_path).schema_arrow.metadata[b"geo"])
    assert metadata["version"] == "1.1.0"
    assert metadata["primary_column"] == "cell_geometry"
    for geometry in metadata["columns"].values():
        assert geometry["encoding"] == "WKB"
        assert geometry["crs"]["id"] == {"authority": "EPSG", "code": 4326}
        assert len(geometry["bbox"]) == 4
    assert cell_part.row_count == dimension.num_rows
    assert fact_part.row_count == facts.num_rows
    assert not (temp_dir / "_SUCCESS").exists()

    connection = duckdb.connect()
    connection.execute("LOAD spatial")
    cell_count = connection.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(cell_path)]
    ).fetchone()[0]
    fact_count = connection.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(fact_path)]
    ).fetchone()[0]
    geometry_count = connection.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE ST_GeometryType(cell_geometry) = 'POLYGON'",
        [str(cell_path)],
    ).fetchone()[0]
    assert (cell_count, fact_count, geometry_count) == (
        dimension.num_rows,
        facts.num_rows,
        dimension.num_rows,
    )
