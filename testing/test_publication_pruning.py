"""Origin partition and pruning tests."""

import pyarrow as pa

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
            "origin_h3_id_hex": route["destination_h3_id_hex"],
            "destination_h3_id_hex": route["origin_h3_id_hex"],
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

    selected_origin = "8928308280fffff"
    selected, files_read = read_origin_facts(parts, selected_origin)

    assert files_read == 1
    assert set(selected.column("origin_h3_id_hex").to_pylist()) == {selected_origin}
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


def test_origin_pruning_is_preserved_after_publication_compaction(temp_dir) -> None:
    dimension, facts = make_publication_tables()
    rows = facts.to_pylist()
    route = next(row for row in rows if row["solve_status"] == "solved")
    reverse = {
        **route,
        "origin_h3_id_hex": route["destination_h3_id_hex"],
        "destination_h3_id_hex": route["origin_h3_id_hex"],
        "origin_representative_snap_distance_m": route[
            "destination_representative_snap_distance_m"
        ],
        "destination_representative_snap_distance_m": route[
            "origin_representative_snap_distance_m"
        ],
        "work_item_id": "work-reverse",
    }
    facts = type(facts).from_pylist([*rows, reverse], schema=facts.schema)
    origin = "8928308280fffff"
    destination = "8928308280bffff"
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
    assert set(selected.column("origin_h3_id_hex").to_pylist()) == {origin}
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
