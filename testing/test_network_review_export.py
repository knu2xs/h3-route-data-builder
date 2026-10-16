"""ArcPy tests for exporting completed eligibility runs as review hexagon feature classes."""

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

pytest.importorskip("arcpy")

from h3_route_data_builder.eligibility.cells import h3_cell_boundary  # noqa: E402
from h3_route_data_builder.network import review_export  # noqa: E402
from h3_route_data_builder.network.review_export import (  # noqa: E402
    export_eligibility_review_feature_class,
)

SYSTEM_FIELD_NAMES = {"objectid", "shape", "shape_length", "shape_area"}


def _manifest(run_directory: Path) -> dict:
    return json.loads((run_directory / "run-manifest.json").read_text(encoding="utf-8"))


def _geoparquet_rows(run_directory: Path) -> list[tuple[str, str]]:
    rows = sorted(
        (row["h3_id"], row["eligibility_status"])
        for part in _manifest(run_directory)["parts"]
        for row in pq.read_table(run_directory / part["path"]).to_pylist()
    )
    return [(str(h3_id), status) for h3_id, status in rows]


def _feature_rows(arcpy: Any, feature_class: Path, fields: list[str]) -> list[tuple]:
    with arcpy.da.SearchCursor(
        str(feature_class), fields, sql_clause=(None, "ORDER BY OBJECTID")
    ) as cursor:
        return [tuple(row) for row in cursor]


def _user_fields(arcpy: Any, feature_class: Path) -> dict[str, Any]:
    return {
        field.name: field
        for field in arcpy.ListFields(str(feature_class))
        if field.name.casefold() not in SYSTEM_FIELD_NAMES
    }


def _snapshot(run_directory: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(run_directory).as_posix(): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(run_directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def review_target(temp_gdb: Path) -> Path:
    return temp_gdb / "eligibility_review"


def test_export_creates_polygon_feature_class_in_wgs84(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    description = arcpy_module.Describe(str(review_target))
    assert description.shapeType == "Polygon"
    assert description.spatialReference.factoryCode == 4326


def test_export_h3_index_field_is_text_length_20(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    h3_index_field = _user_fields(arcpy_module, review_target)["h3_index"]
    assert (h3_index_field.type, h3_index_field.length) == ("String", 20)


def test_export_eligibility_status_field_is_text_length_32(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    status_field = _user_fields(arcpy_module, review_target)["eligibility_status"]
    assert (status_field.type, status_field.length) == ("String", 32)


def test_export_has_no_extra_user_fields(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    assert set(_user_fields(arcpy_module, review_target)) == {
        "h3_index",
        "eligibility_status",
    }


def test_export_row_count_equals_manifest_cell_result_count(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    row_count = int(arcpy_module.management.GetCount(str(review_target))[0])
    assert row_count == _manifest(arcpy_completed_eligibility_run)["cell_result_count"]


def test_export_h3_index_and_status_match_geoparquet_in_ascending_order(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    rows = _feature_rows(arcpy_module, review_target, ["h3_index", "eligibility_status"])
    assert rows == _geoparquet_rows(arcpy_completed_eligibility_run)


def test_export_polygon_vertices_match_h3_boundary(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    for h3_index, shape in _feature_rows(arcpy_module, review_target, ["h3_index", "SHAPE@"]):
        ring = [(point.X, point.Y) for point in shape.getPart(0)][:-1]
        expected = h3_cell_boundary(int(h3_index))
        assert len(ring) == len(expected)
        for expected_lon, expected_lat in expected:
            assert any(
                abs(lon - expected_lon) <= 1e-9 and abs(lat - expected_lat) <= 1e-9
                for lon, lat in ring
            ), f"Vertex ({expected_lon}, {expected_lat}) missing for {h3_index}"


def test_export_returns_written_feature_count(
    arcpy_completed_eligibility_run: Path,
    review_target: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=review_export.logger.name):
        written = export_eligibility_review_feature_class(
            arcpy_completed_eligibility_run, review_target
        )

    assert written == _manifest(arcpy_completed_eligibility_run)["cell_result_count"]
    info_messages = " ".join(
        record.getMessage() for record in caplog.records if record.levelno == logging.INFO
    )
    assert "Starting" in info_messages
    assert str(review_target) in info_messages
    assert f"{written} features" in info_messages
    assert "Completed" in info_messages


def test_export_does_not_modify_run_directory(
    arcpy_completed_eligibility_run: Path, review_target: Path
) -> None:
    before = _snapshot(arcpy_completed_eligibility_run)

    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    assert _snapshot(arcpy_completed_eligibility_run) == before


def test_export_failure_deletes_partial_feature_class(
    arcpy_module: Any,
    arcpy_completed_eligibility_run: Path,
    review_target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_iter_review_cells = review_export.iter_review_cells

    def failing_iter(run_directory: Path) -> Iterator[Any]:
        cells = real_iter_review_cells(run_directory)

        def _generate() -> Iterator[Any]:
            yield next(iter(cells))
            raise ValueError("simulated read failure")

        return _generate()

    monkeypatch.setattr(review_export, "iter_review_cells", failing_iter)

    with pytest.raises(ValueError, match="simulated read failure"):
        export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)
    assert not arcpy_module.Exists(str(review_target))


def test_export_count_mismatch_deletes_feature_class_and_raises(
    arcpy_module: Any,
    arcpy_completed_eligibility_run: Path,
    review_target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _manifest(arcpy_completed_eligibility_run)["cell_result_count"]
    monkeypatch.setattr(review_export, "expected_review_cell_count", lambda _: expected + 1)

    with pytest.raises(ValueError, match="count"):
        export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)
    assert not arcpy_module.Exists(str(review_target))


def test_export_zero_cells_creates_empty_feature_class_and_warns(
    arcpy_module: Any,
    arcpy_completed_eligibility_run: Path,
    review_target: Path,
    manifest_rewriter: Callable[..., None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    partition_keys = _manifest(arcpy_completed_eligibility_run)["expected_partition_keys"]
    manifest_rewriter(
        arcpy_completed_eligibility_run,
        parts=[],
        partition_summaries={
            key: {"cell_result_count": 0, "solvable_cell_count": 0} for key in partition_keys
        },
        cell_result_count=0,
        solvable_cell_count=0,
    )

    with caplog.at_level(logging.WARNING, logger=review_export.logger.name):
        written = export_eligibility_review_feature_class(
            arcpy_completed_eligibility_run, review_target
        )

    assert written == 0
    assert int(arcpy_module.management.GetCount(str(review_target))[0]) == 0
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_export_failure_leaves_run_status_complete(
    arcpy_completed_eligibility_run: Path,
    review_target: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review_export, "expected_review_cell_count", lambda _: -1)

    with pytest.raises(ValueError):
        export_eligibility_review_feature_class(arcpy_completed_eligibility_run, review_target)

    assert _manifest(arcpy_completed_eligibility_run)["run_status"] == "complete"


def test_export_of_resumed_completed_run_is_identical(
    arcpy_module: Any, arcpy_completed_eligibility_run: Path, temp_gdb: Path
) -> None:
    first_target = temp_gdb / "first_review"
    second_target = temp_gdb / "second_review"
    fields = ["h3_index", "eligibility_status", "SHAPE@WKB"]

    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, first_target)
    export_eligibility_review_feature_class(arcpy_completed_eligibility_run, second_target)

    first_rows = [
        (h3_index, status, bytes(wkb))
        for h3_index, status, wkb in _feature_rows(arcpy_module, first_target, fields)
    ]
    second_rows = [
        (h3_index, status, bytes(wkb))
        for h3_index, status, wkb in _feature_rows(arcpy_module, second_target, fields)
    ]
    assert first_rows == second_rows
