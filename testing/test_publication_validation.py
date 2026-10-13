"""Publication integrity and expected-key validation tests."""

import pytest
import pyarrow.compute as pc

from h3_route_data_builder.od.results import OutcomeClass, SolveOutcome
from h3_route_data_builder.publication.validation import (
    validate_parts,
    validate_publication,
)
from h3_route_data_builder.publication.write import write_table
from testing.publication_fixtures import (
    make_outcome,
    make_publication_tables,
)


def test_publication_reconciles_qualifying_outcomes_and_self_pairs() -> None:
    dimension, facts = make_publication_tables()
    origin = "8928308280fffff"
    destination = "8928308280bffff"
    outcome = make_outcome(origin, destination)

    report = validate_publication(
        dimension,
        facts,
        expected_keys=[(origin, destination), (origin, origin)],
        outcomes=[outcome],
        self_pairs=[(origin, origin)],
        build_fingerprint="result-fingerprint",
    )

    assert report.valid
    assert report.errors == ()
    assert report.outcome_counts == {"qualifying": 1, "self_pair": 1}


@pytest.mark.parametrize(
    "classification", [OutcomeClass.UNLOCATED, OutcomeClass.UNREACHABLE]
)
def test_nonroute_outcomes_resolve_expected_key_without_fact(classification) -> None:
    dimension, facts = make_publication_tables()
    origin = "8928308280fffff"
    destination = "8928308280bffff"
    nonroute = SolveOutcome((origin, destination), classification, None, None)
    facts_without_route = facts.filter(
        pc.equal(facts.column("solve_status"), "self_pair")
    )

    report = validate_publication(
        dimension,
        facts_without_route,
        expected_keys=[(origin, destination), (origin, origin)],
        outcomes=[nonroute],
        self_pairs=[(origin, origin)],
        build_fingerprint="result-fingerprint",
    )

    assert report.valid
    assert report.outcome_counts[classification.value] == 1


def test_validation_rejects_missing_duplicate_unexpected_and_incompatible_keys() -> (
    None
):
    dimension, facts = make_publication_tables()
    origin = "8928308280fffff"
    destination = "8928308280bffff"
    report = validate_publication(
        dimension,
        facts,
        expected_keys=[(origin, destination)],
        outcomes=[make_outcome(origin, destination), make_outcome(origin, destination)],
        self_pairs=[],
        build_fingerprint="different-fingerprint",
    )

    assert not report.valid
    assert any("duplicate" in error.casefold() for error in report.errors)
    assert any("unexpected" in error.casefold() for error in report.errors)
    assert any("fingerprint" in error.casefold() for error in report.errors)


def test_validation_rejects_retryable_ledger_state() -> None:
    dimension, facts = make_publication_tables()
    origin = "8928308280fffff"
    destination = "8928308280bffff"
    key = (origin, destination)
    report = validate_publication(
        dimension,
        facts,
        expected_keys=[key, (origin, origin)],
        outcomes=[make_outcome(origin, destination)],
        self_pairs=[(origin, origin)],
        build_fingerprint="result-fingerprint",
        solve_states={key: "retryable_failure"},
    )

    assert not report.valid
    assert any("not committed" in error for error in report.errors)


def test_part_validation_rejects_checksum_corruption(temp_dir) -> None:
    dimension, _ = make_publication_tables()
    part = write_table(dimension, temp_dir / "cells.parquet", "solvable_cells")
    part.path.write_bytes(b"corrupt")

    errors = validate_parts([part])

    assert any("checksum" in error.casefold() for error in errors)
