"""Acceptance tests for exact portable integer H3 identities."""

import json
import subprocess
import sys

from h3.api import basic_int as h3
import pytest

from h3_route_data_builder.eligibility.cells import (
    canonical_h3_ids,
    h3_candidate_ids,
    h3_cell_boundary,
)


def test_canonical_cells_are_exact_sorted_integers(
    integer_h3_cells: tuple[int, ...],
) -> None:
    result = canonical_h3_ids(reversed(integer_h3_cells + integer_h3_cells))
    assert result == sorted(set(integer_h3_cells))
    assert all(type(cell) is int and cell > 2**53 for cell in result)
    assert {h3.get_resolution(cell) for cell in result} == set(range(16))
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize(
    "value",
    [
        "89754e64993ffff",
        "619056821840379903",
        True,
        False,
        1.0,
        None,
        -1,
        0,
        2**64 - 1,
        2**64,
    ],
)
def test_canonicalization_rejects_non_cell_identity(value: object) -> None:
    with pytest.raises(ValueError, match="Invalid H3 cell ID"):
        canonical_h3_ids([value])


@pytest.mark.parametrize("value", ["89754e64993ffff", True, 1.0, None, -1, 0, 2**64])
def test_boundary_rejects_non_cell_identity(value: object) -> None:
    with pytest.raises(ValueError, match="Invalid H3 cell ID"):
        h3_cell_boundary(value)


def test_cover_and_boundaries_preserve_cells_and_coordinates() -> None:
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]],
    }
    result = h3_candidate_ids(polygon, 9)
    expected = sorted(
        h3.h3shape_to_cells_experimental(h3.geo_to_h3shape(polygon), 9, contain="bbox_overlap")
    )
    assert result == expected
    assert all(type(cell) is int for cell in result)
    assert h3_cell_boundary(result[0]) == tuple(
        (longitude, latitude) for latitude, longitude in h3.cell_to_boundary(result[0])
    )


@pytest.mark.parametrize("resolution", [-1, 16, True, 1.0, None])
def test_cover_rejects_invalid_resolution(resolution: object) -> None:
    with pytest.raises(ValueError, match="resolution"):
        h3_candidate_ids({}, resolution)


def test_cell_helpers_import_without_arcpy() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['arcpy'] = None; "
            "from h3_route_data_builder.eligibility.cells import canonical_h3_ids; "
            "assert canonical_h3_ids([]) == []",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
