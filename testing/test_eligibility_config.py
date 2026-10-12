"""Tests for required eligibility configuration validation."""

import pytest

from h3_route_data_builder.config import ConfigNode, config as project_config
from h3_route_data_builder.eligibility.config import eligibility_config_from_node


def make_config(**overrides: object) -> ConfigNode:
    """Build valid test configuration with optional section overrides."""
    values: dict[str, dict[str, object]] = {
        "spatial": {
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
        },
    }
    for section, section_values in overrides.items():
        if section in values and isinstance(section_values, dict):
            values[section].update(section_values)
    return ConfigNode(values)


def test_valid_eligibility_config_is_extracted_and_normalized() -> None:
    config = make_config(network={"restrictions": ["Truck", "Automobile", "Truck"]})

    result = eligibility_config_from_node(config)

    assert result.restrictions == ("Automobile", "Truck")
    assert result.representative_snap_tolerance_m == 0.01


def test_invalid_h3_resolution_is_rejected() -> None:
    config = make_config(spatial={"h3_resolution": 16})

    with pytest.raises(ValueError, match="between 0 and 15"):
        eligibility_config_from_node(config)


def test_project_config_default_snap_tolerance_is_used_by_api() -> None:
    values = project_config.to_dict()
    values["spatial"]["h3_resolution"] = 9
    values["network"]["travel_mode"] = "Driving Time"

    result = eligibility_config_from_node(ConfigNode(values))

    assert result.representative_snap_tolerance_m == 100.0
