"""Tests for required eligibility configuration validation."""

import pytest

from h3_route_data_builder.config import ConfigNode
from h3_route_data_builder.eligibility.config import eligibility_config_from_node


def make_config(**overrides: object) -> ConfigNode:
    """Build valid test configuration with optional section overrides."""
    values: dict[str, dict[str, object]] = {
        "spatial": {
            "working_crs": "projected-test-crs",
            "storage_crs": "GCS_WGS_1984",
            "datum_transformation": None,
            "h3_resolution": 9,
            "intersection_policy": "inclusive",
            "representative_snap_tolerance_m": 0.01,
        },
        "network": {
            "travel_mode": "Driving Time",
            "restrictions": ["Driving an Automobile"],
        },
        "eligibility": {
            "representative_policy": "nearest_centroid_then_source_id_oid_measure",
            "batch_size": 100,
            "part_row_limit": 1000,
            "total_output_hard_cap": 100000,
        },
    }
    for section, section_values in overrides.items():
        if section in values and isinstance(section_values, dict):
            values[section].update(section_values)
    return ConfigNode(values)


def test_valid_eligibility_config_is_extracted_and_normalized() -> None:
    config = make_config(network={"restrictions": ["Truck", "Automobile", "Truck"]})

    result = eligibility_config_from_node(config)

    assert result.working_crs == "projected-test-crs"
    assert result.storage_crs == "GCS_WGS_1984"
    assert result.datum_transformation is None
    assert result.restrictions == ("Automobile", "Truck")
    assert result.total_output_hard_cap == 100000


def test_missing_working_crs_is_rejected_without_a_default() -> None:
    config = make_config(spatial={"working_crs": None})

    with pytest.raises(ValueError, match="spatial.working_crs"):
        eligibility_config_from_node(config)


def test_invalid_h3_resolution_is_rejected() -> None:
    config = make_config(spatial={"h3_resolution": 16})

    with pytest.raises(ValueError, match="between 0 and 15"):
        eligibility_config_from_node(config)


@pytest.mark.parametrize(
    "key", ["batch_size", "part_row_limit", "total_output_hard_cap"]
)
def test_non_positive_capacity_values_are_rejected(key: str) -> None:
    config = make_config(eligibility={key: 0})

    with pytest.raises(ValueError, match="must be positive"):
        eligibility_config_from_node(config)
