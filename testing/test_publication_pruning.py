"""Origin partition and pruning tests."""

import pyarrow as pa
import pytest

from h3_route_data_builder.publication.partition import read_origin_facts
from h3_route_data_builder.publication.compact import compact_publication
from h3_route_data_builder.publication.models import PublishedPart
from h3_route_data_builder.publication.publish import publish_dataset
from h3_route_data_builder.publication.write import write_table
from testing.publication_fixtures import make_outcome, make_publication_tables


def test_origin_partition_reads_only_the_selected_origin(temp_dir) -> None:
    _, facts = make_publication_tables()
    rows = facts.to_pylist()
    route = next(row for row in rows if row["solve_status"] == "solved")
    rows.append(
        {
            **route,
            "origin_h3_id": route["destination_h3_id"],
            "destination_h3_id": route["origin_h3_id"],
            "origin_representative_snap_distance_m": route[
                "destination_representative_snap_distance_m"
            ],
            "destination_representative_snap_distance_m": route[
                "origin_representative_snap_distance_m"
            ],
            "work_item_id": "work-reverse",
        }
    )
    facts = pa.Table.from_pylist(rows, schema=facts.schema)
    parts = write_table(
        facts,
        temp_dir / "parts",
        table_name="od_facts",
        partition_by_origin=True,
    )

    selected_origin = 617700169958293503
    selected, files_read = read_origin_facts(parts, selected_origin)

    assert files_read == 1
    assert set(selected.column("origin_h3_id").to_pylist()) == {selected_origin}
    assert len(parts) == 2


def test_fact_parts_obey_the_configured_row_limit(temp_dir) -> None:
    _, facts = make_publication_tables()

    parts = write_table(
        facts,
        temp_dir / "bounded-parts",
        table_name="od_facts",
        partition_by_origin=True,
        part_row_limit=1,
    )

    assert len(parts) == facts.num_rows
    assert all(part.row_count <= 1 for part in parts)


@pytest.mark.parametrize("origin", ["8928308280fffff", "617700169958293503", True, 1.0, None])
def test_origin_pruning_rejects_noncanonical_api_input(origin: object) -> None:
    with pytest.raises(ValueError, match="H3"):
        read_origin_facts([], origin)


def test_origin_identity_comes_from_typed_columns_not_directory_labels(temp_dir) -> None:
    _, facts = make_publication_tables()
    path = temp_dir / "origin_h3_id=0" / "misleading-label.parquet"
    part = write_table(facts, path, table_name="od_facts")
    origin = facts.column("origin_h3_id")[0].as_py()
    selected, count = read_origin_facts([part], origin)
    assert count == 1
    assert set(selected.column("origin_h3_id").to_pylist()) == {origin}


def test_origin_pruning_is_preserved_after_publication_compaction(temp_dir) -> None:
    dimension, facts = make_publication_tables()
    rows = facts.to_pylist()
    route = next(row for row in rows if row["solve_status"] == "solved")
    reverse = {
        **route,
        "origin_h3_id": route["destination_h3_id"],
        "destination_h3_id": route["origin_h3_id"],
        "origin_representative_snap_distance_m": route[
            "destination_representative_snap_distance_m"
        ],
        "destination_representative_snap_distance_m": route[
            "origin_representative_snap_distance_m"
        ],
        "work_item_id": "work-reverse",
    }
    facts = type(facts).from_pylist([*rows, reverse], schema=facts.schema)
    origin = 617700169958293503
    destination = 617700169958031359
    root = temp_dir / "store"
    source = publish_dataset(
        root,
        dimension,
        facts,
        [(origin, destination), (destination, origin), (origin, origin)],
        [
            make_outcome(origin, destination),
            make_outcome(destination, origin),
        ],
        [(origin, origin)],
        "dataset-fingerprint",
        "result-fingerprint",
        "eligibility-fingerprint",
        {"mode": "aoi_only"},
        {"state": "complete"},
    )
    compacted = compact_publication(root, source.version_id)
    parts = _fact_parts(compacted)
    selected, files_read = read_origin_facts(parts, origin)

    assert files_read == 1
    assert set(selected.column("origin_h3_id").to_pylist()) == {origin}
    assert len(parts) == 2


def _fact_parts(publication) -> list[PublishedPart]:
    fact_partition = next(
        partition
        for partition in publication.manifest.partition_manifests
        if partition.table_name == "od_facts"
    )
    return [
        PublishedPart(
            table_name=part.table_name,
            path=publication.version_path / part.path,
            row_count=part.row_count,
            checksum=part.checksum,
            schema_version=part.schema_version,
            extent=part.extent,
            origin_ids=part.origin_ids,
        )
        for part in fact_partition.parts
    ]
