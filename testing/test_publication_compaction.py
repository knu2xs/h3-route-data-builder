"""Immutable compaction equivalence tests."""

from h3_route_data_builder.publication.compact import compact_publication
from h3_route_data_builder.publication.publish import (
    publish_dataset,
    read_current_publication,
)
from testing.publication_fixtures import make_outcome, make_publication_tables


def test_compaction_creates_new_version_without_changing_source(temp_dir) -> None:
    dimension, facts = make_publication_tables()
    origin, destination = 617700169958293503, 617700169958031359
    root = temp_dir / "store"
    source = publish_dataset(
        root,
        dimension,
        facts,
        [(origin, destination), (origin, origin)],
        [make_outcome(origin, destination)],
        [(origin, origin)],
        "dataset-fingerprint",
        "result-fingerprint",
        "eligibility-fingerprint",
        {"mode": "aoi_only"},
        {"state": "complete"},
    )
    original_cell_bytes = (source.version_path / "solvable_cells.parquet").read_bytes()

    compacted = compact_publication(root, source.version_id)
    current = read_current_publication(root)

    assert compacted.version_id != source.version_id
    assert current.version_id == compacted.version_id
    assert (source.version_path / "solvable_cells.parquet").read_bytes() == original_cell_bytes
    assert current.dimension.to_pylist() == dimension.to_pylist()
    assert {
        (row["origin_h3_id"], row["destination_h3_id"]) for row in current.facts.to_pylist()
    } == {(row["origin_h3_id"], row["destination_h3_id"]) for row in facts.to_pylist()}
