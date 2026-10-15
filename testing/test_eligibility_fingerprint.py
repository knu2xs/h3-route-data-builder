"""Tests for deterministic eligibility fingerprints."""

import pytest

from h3_route_data_builder.eligibility.fingerprint import build_input_fingerprint


def make_fingerprint(**overrides: object) -> str:
    """Build a fingerprint using stable test inputs."""
    values: dict[str, object] = {
        "aoi_fingerprint": "aoi-1",
        "network_fingerprint": "network-1",
        "travel_mode": "Driving Time",
        "restrictions": ["OneWay", "PrivateRoad"],
        "h3_resolution": 9,
        "eligibility_policy": {
            "intersection": "inclusive",
            "tie_break": ["source", "oid"],
        },
        "schema_version": "2",
        "software_versions": {
            "python": "3.13",
            "arcgis_pro": "3.7",
            "h3": "4.2",
            "package": "0.1",
        },
    }
    values.update(overrides)
    return build_input_fingerprint(**values)  # type: ignore[arg-type]


def test_fingerprint_is_stable_when_mapping_and_restriction_order_changes() -> None:
    first = make_fingerprint(
        eligibility_policy={
            "intersection": "inclusive",
            "tie_break": ["source", "oid"],
        },
        restrictions=["OneWay", "PrivateRoad"],
    )
    second = make_fingerprint(
        eligibility_policy={
            "tie_break": ["source", "oid"],
            "intersection": "inclusive",
        },
        restrictions=["PrivateRoad", "OneWay"],
    )

    assert first == second


def test_fingerprint_changes_when_output_policy_changes() -> None:
    baseline = make_fingerprint()
    changed = make_fingerprint(eligibility_policy={"intersection": "interior_only"})

    assert baseline != changed


def test_fingerprint_requires_software_versions() -> None:
    with pytest.raises(ValueError, match="Missing software versions"):
        make_fingerprint(software_versions={"python": "3.13"})


def test_integer_schema_fingerprint_does_not_adopt_legacy_identity() -> None:
    assert make_fingerprint() != make_fingerprint(schema_version="1")
