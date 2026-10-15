"""GeoParquet writer and independent-reader interoperability tests."""

import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from h3_route_data_builder.publication.convert import outcomes_to_table, solvable_cells_to_table
from testing.publication_fixtures import make_cell, make_geometry_map, make_outcome
from h3_route_data_builder.publication.write import write_table
from testing.publication_fixtures import make_publication_tables


@pytest.mark.parametrize("resolution", range(16))
def test_greatest_valid_cells_round_trip_in_arrow_and_duckdb(
    tmp_path: Path,
    integer_h3_cells: tuple[int, ...],
    resolution: int,
) -> None:
    ids = sorted(integer_h3_cells[resolution * 4 + 2 : resolution * 4 + 4])
    cells = [make_cell(cell_id) for cell_id in ids]
    dimension = solvable_cells_to_table(cells, make_geometry_map(cells))
    path = tmp_path / "all-resolutions.parquet"
    write_table(dimension, path, table_name="solvable_cells")
    assert pq.ParquetFile(path).read().column("h3_id").to_pylist() == ids
    with duckdb.connect() as connection:
        actual = connection.execute(
            "SELECT h3_id FROM read_parquet(?) ORDER BY h3_id",
            [str(path)],
        ).fetchall()
    assert actual == [(cell_id,) for cell_id in ids]


@pytest.mark.parametrize("table_name", ["solvable_cells", "od_facts"])
def test_writer_rejects_legacy_schema_identity_even_with_integer_columns(
    tmp_path: Path,
    table_name: str,
) -> None:
    dimension, facts = make_publication_tables()
    table = dimension if table_name == "solvable_cells" else facts
    metadata = dict(table.schema.metadata)
    metadata[b"schema_version"] = b"1.0.0"
    with pytest.raises(ValueError, match="schema"):
        write_table(
            table.replace_schema_metadata(metadata), tmp_path / "invalid.parquet", table_name
        )
    assert not (tmp_path / "invalid.parquet").exists()


def test_integer_contract_round_trips_exact_reverse_and_self_keys(
    tmp_path: Path,
    integer_od_keys: tuple[tuple[int, int], ...],
) -> None:
    ids = sorted({endpoint for key in integer_od_keys for endpoint in key})
    cells = [make_cell(cell_id) for cell_id in ids]
    dimension = solvable_cells_to_table(cells, make_geometry_map(cells))
    outcomes = [make_outcome(*key) for key in integer_od_keys if key[0] != key[1]]
    facts = outcomes_to_table(
        outcomes,
        [key for key in integer_od_keys if key[0] == key[1]],
        dimension,
        "Driving Time",
        "integer-contract",
        "distance",
        {outcome.logical_od_key: f"work-{index}" for index, outcome in enumerate(outcomes)},
    )
    path = tmp_path / "integer-facts.parquet"
    part = write_table(facts, path, table_name="od_facts")
    assert part.to_dict()["origin_ids"] == ids
    assert all(type(value) is int and value > 2**53 for value in part.origin_ids)
    loaded = pq.ParquetFile(path).read()
    assert loaded.schema.field("origin_h3_id").type == pa.uint64()
    assert loaded.equals(facts)
    with duckdb.connect() as connection:
        actual = connection.execute(
            "SELECT origin_h3_id, destination_h3_id FROM read_parquet(?) ORDER BY 1, 2",
            [str(path)],
        ).fetchall()
    assert actual == sorted(integer_od_keys)
    assert dimension.schema.metadata[b"schema_version"] == b"2.0.0"


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
