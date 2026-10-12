"""Tests for the ArcPy-free eligibility output table contract."""

import json

import pyarrow as pa
import pytest

from h3_route_data_builder.eligibility.models import (
    CellEligibilityResult,
    EligibilityStatus,
    NetworkLocation,
)
from h3_route_data_builder.eligibility.output import eligibility_results_to_table


def make_result(status: EligibilityStatus) -> CellEligibilityResult:
    """Create a cell result for output-schema assertions."""
    representative = (
        NetworkLocation(1, 2, 3, 4, 0.5, 1, 0.0)
        if status == EligibilityStatus.SOLVABLE
        else None
    )
    return CellEligibilityResult(
        h3_id_hex="8928308280fffff",
        resolution=9,
        eligibility_status=status,
        eligibility_reason="validated" if representative else "no eligible edge",
        intersecting_edge_count=1 if representative else 0,
        representative=representative,
        build_fingerprint="fingerprint",
    )


def test_output_table_has_required_geoparquet_and_location_fields() -> None:
    result = make_result(EligibilityStatus.SOLVABLE)
    table = eligibility_results_to_table(
        [result],
        {result.h3_id_hex: (b"cell-wkb", b"centroid-wkb", b"representative-wkb")},
    )
    geo_metadata = json.loads(table.schema.metadata[b"geo"])

    assert table.column("h3_id_hex").to_pylist() == [result.h3_id_hex]
    assert table.column("network_source_id").to_pylist() == [3]
    assert table.column("network_source_oid").to_pylist() == [4]
    assert table.column("pos_along").to_pylist() == [0.5]
    assert table.column("side_of_edge").to_pylist() == [1]
    assert set(geo_metadata["columns"]) == {
        "cell_geometry",
        "centroid_geometry",
        "representative_geometry",
    }
    assert all(
        column["crs"]["id"] == {"authority": "EPSG", "code": 4326}
        for column in geo_metadata["columns"].values()
    )


def test_output_table_keeps_representative_fields_null_for_ineligible_cell() -> None:
    result = make_result(EligibilityStatus.INELIGIBLE)
    table = eligibility_results_to_table(
        [result],
        {result.h3_id_hex: (b"cell-wkb", b"centroid-wkb", None)},
    )

    assert table.column("eligibility_status").to_pylist() == ["ineligible"]
    assert table.column("representative_geometry").to_pylist() == [None]
    assert table.column("network_source_id").to_pylist() == [None]


def test_output_table_requires_cell_and_centroid_geometry() -> None:
    result = make_result(EligibilityStatus.INELIGIBLE)

    with pytest.raises(ValueError, match="Cell and centroid WKB are required"):
        eligibility_results_to_table(
            [result],
            {result.h3_id_hex: (b"", b"centroid-wkb", None)},
        )
