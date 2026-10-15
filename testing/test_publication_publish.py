"""Atomic publication and restart/fault-injection tests."""

import json

import pyarrow as pa
import pytest

from h3_route_data_builder.publication.schema import OD_FACTS_SCHEMA
from h3_route_data_builder.publication.publish import (
    publish_dataset,
    read_current_publication,
)
from testing.publication_fixtures import make_outcome, make_publication_tables


@pytest.mark.parametrize(
    "interrupt_after",
    ["after_staging", "after_validation", "after_manifest", "after_exposure"],
)
def test_restart_recovers_from_each_publication_boundary_without_duplicate_facts(
    temp_dir, interrupt_after
) -> None:
    dimension, facts = make_publication_tables()
    first, second = 617700169958293503, 617700169958031359
    expected = [(first, second), (first, first)]
    outcome = make_outcome(first, second)
    arguments = dict(
        output_root=temp_dir / "store",
        dimension=dimension,
        facts=facts,
        expected_keys=expected,
        outcomes=[outcome],
        self_pairs=[(first, first)],
        dataset_fingerprint="dataset-fingerprint",
        result_compatibility_fingerprint="result-fingerprint",
        eligibility_fingerprint="eligibility-fingerprint",
        candidate_provenance={"mode": "aoi_only"},
        solve_provenance={"state": "complete"},
    )

    def interrupt(phase: str) -> None:
        if phase == interrupt_after:
            raise RuntimeError(f"injected {phase}")

    with pytest.raises(RuntimeError, match="injected"):
        publish_dataset(**arguments, fault_hook=interrupt)
    result = publish_dataset(**arguments)
    current = read_current_publication(arguments["output_root"])

    assert current.version_id == result.version_id
    assert result.success_path.is_file()
    assert json.loads(result.manifest_path.read_text())["status"] == "complete"
    assert (
        len(
            set(
                zip(
                    current.facts.column("origin_h3_id").to_pylist(),
                    current.facts.column("destination_h3_id").to_pylist(),
                )
            )
        )
        == 2
    )


def test_invalid_staged_publication_never_creates_completion_marker_or_current(
    temp_dir,
) -> None:
    dimension, facts = make_publication_tables()
    origin, destination = 617700169958293503, 617700169958031359
    output_root = temp_dir / "invalid-store"

    with pytest.raises(ValueError, match="Missing authoritative outcome"):
        publish_dataset(
            output_root,
            dimension,
            facts,
            [(origin, destination), (origin, origin), (destination, origin)],
            [make_outcome(origin, destination)],
            [(origin, origin)],
            "dataset-fingerprint",
            "result-fingerprint",
            "eligibility-fingerprint",
            {"mode": "aoi_only"},
            {"state": "complete"},
        )

    assert not (output_root / "CURRENT").exists()
    assert not list((output_root / "versions").glob("*/_SUCCESS"))


def test_corrupt_published_part_is_not_read_as_complete(temp_dir) -> None:
    dimension, facts = make_publication_tables()
    origin, destination = 617700169958293503, 617700169958031359
    output_root = temp_dir / "corrupt-store"
    result = publish_dataset(
        output_root,
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
    (result.version_path / "solvable_cells.parquet").write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="checksum"):
        read_current_publication(output_root)


def test_historical_schema_is_rejected_without_relabeling_or_rewriting(temp_dir) -> None:
    dimension, facts = make_publication_tables()
    origin, destination = 617700169958293503, 617700169958031359
    root = temp_dir / "history"
    result = publish_dataset(
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
    document = json.loads(result.manifest_path.read_text())
    document["schema_versions"] = {
        "dataset": "1.0.0",
        "solvable_cells": "1.0.0",
        "od_facts": "1.0.0",
    }
    result.manifest_path.write_text(json.dumps(document))
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    with pytest.raises(ValueError, match="schema versions"):
        read_current_publication(root)
    assert {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == before


def test_empty_publication_has_valid_zero_counts_and_completion(temp_dir) -> None:
    from h3_route_data_builder.publication.convert import solvable_cells_to_table

    dimension = solvable_cells_to_table([], {})
    facts = pa.Table.from_pylist([], schema=OD_FACTS_SCHEMA)
    output_root = temp_dir / "empty-store"

    result = publish_dataset(
        output_root,
        dimension,
        facts,
        [],
        [],
        [],
        "empty-dataset",
        "empty-result",
        "empty-eligibility",
        {"mode": "aoi_only"},
        {"state": "complete"},
    )
    current = read_current_publication(output_root)

    assert result.success_path.is_file()
    assert current.dimension.num_rows == 0
    assert current.facts.num_rows == 0
    assert current.manifest["expected_key_count"] == 0
