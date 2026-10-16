"""ArcPy-free tests for streaming review cells from a completed eligibility run."""

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from h3_route_data_builder.eligibility.review import (
    ReviewCell,
    expected_review_cell_count,
    iter_review_cells,
)


def _manifest(run_directory: Path) -> dict:
    return json.loads((run_directory / "run-manifest.json").read_text(encoding="utf-8"))


def _listed_part_tables(run_directory: Path) -> list[pa.Table]:
    return [
        pq.read_table(run_directory / part["path"]) for part in _manifest(run_directory)["parts"]
    ]


def _replace_first_part_column(
    run_directory: Path,
    column_name: str,
    transform: Callable[[list], list],
) -> None:
    """Rewrite one listed part column and update its checksum so only content is invalid."""
    manifest = _manifest(run_directory)
    part = manifest["parts"][0]
    part_path = run_directory / part["path"]
    table = pq.read_table(part_path)
    column_index = table.schema.get_field_index(column_name)
    field = table.schema.field(column_index)
    values = transform(table.column(column_name).to_pylist())
    table = table.set_column(column_index, field, pa.array(values, type=field.type))
    pq.write_table(table, part_path)
    part["checksum"] = hashlib.sha256(part_path.read_bytes()).hexdigest()
    (run_directory / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_iter_review_cells_yields_every_manifest_row(
    completed_eligibility_run: Path,
) -> None:
    cells = list(iter_review_cells(completed_eligibility_run))

    assert len(cells) == _manifest(completed_eligibility_run)["cell_result_count"]
    assert all(isinstance(cell, ReviewCell) for cell in cells)


def test_iter_review_cells_orders_h3_ids_strictly_ascending_across_partitions(
    completed_eligibility_run: Path,
) -> None:
    h3_ids = [cell.h3_id for cell in iter_review_cells(completed_eligibility_run)]

    assert all(earlier < later for earlier, later in zip(h3_ids, h3_ids[1:]))


def test_iter_review_cells_preserves_eligibility_status_and_geometry_wkb(
    completed_eligibility_run: Path,
) -> None:
    expected = {
        row["h3_id"]: (row["eligibility_status"], row["cell_geometry"])
        for table in _listed_part_tables(completed_eligibility_run)
        for row in table.to_pylist()
    }

    actual = {
        cell.h3_id: (cell.eligibility_status, cell.cell_geometry_wkb)
        for cell in iter_review_cells(completed_eligibility_run)
    }

    assert actual == expected
    assert {status for status, _ in actual.values()} == {"solvable", "ineligible"}


def test_iter_review_cells_ignores_unlisted_stale_part_files(
    completed_eligibility_run: Path,
) -> None:
    first_part = (
        completed_eligibility_run / _manifest(completed_eligibility_run)["parts"][0]["path"]
    )
    stale_part = first_part.with_name("stale-unlisted.parquet")
    stale_part.write_bytes(first_part.read_bytes())

    cells = list(iter_review_cells(completed_eligibility_run))

    assert len(cells) == _manifest(completed_eligibility_run)["cell_result_count"]


def test_iter_review_cells_resolves_part_paths_relative_to_run_directory(
    completed_eligibility_run: Path,
) -> None:
    moved_run = completed_eligibility_run.with_name("moved-run")
    completed_eligibility_run.rename(moved_run)

    cells = list(iter_review_cells(moved_run))

    assert len(cells) == _manifest(moved_run)["cell_result_count"]


def test_expected_review_cell_count_returns_manifest_cell_result_count(
    completed_eligibility_run: Path,
) -> None:
    expected = _manifest(completed_eligibility_run)["cell_result_count"]

    assert expected_review_cell_count(completed_eligibility_run) == expected


def test_review_module_does_not_import_arcpy() -> None:
    probe = (
        "import sys\n"
        "import h3_route_data_builder.eligibility.review\n"
        "assert 'arcpy' not in sys.modules, 'arcpy was imported'\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr


def test_iter_review_cells_rejects_incomplete_run(
    completed_eligibility_run: Path, manifest_rewriter: Callable[..., None]
) -> None:
    manifest_rewriter(completed_eligibility_run, run_status="running")

    with pytest.raises(ValueError, match="not complete"):
        list(iter_review_cells(completed_eligibility_run))


def test_iter_review_cells_rejects_missing_manifest(
    completed_eligibility_run: Path,
) -> None:
    (completed_eligibility_run / "run-manifest.json").unlink()

    with pytest.raises(ValueError, match="manifest"):
        list(iter_review_cells(completed_eligibility_run))


def test_iter_review_cells_rejects_part_checksum_mismatch(
    completed_eligibility_run: Path,
) -> None:
    first_part = (
        completed_eligibility_run / _manifest(completed_eligibility_run)["parts"][0]["path"]
    )
    first_part.write_bytes(first_part.read_bytes() + b"corrupt")

    with pytest.raises(ValueError, match="checksum"):
        list(iter_review_cells(completed_eligibility_run))


def test_iter_review_cells_rejects_invalid_h3_id(
    completed_eligibility_run: Path,
) -> None:
    _replace_first_part_column(completed_eligibility_run, "h3_id", lambda ids: [0, *ids[1:]])

    with pytest.raises(ValueError, match="H3"):
        list(iter_review_cells(completed_eligibility_run))


def test_iter_review_cells_rejects_wrong_resolution(
    completed_eligibility_run: Path, manifest_rewriter: Callable[..., None]
) -> None:
    resolution = _manifest(completed_eligibility_run)["policy"]["h3_resolution"]
    manifest_rewriter(completed_eligibility_run, policy={"h3_resolution": resolution - 1})

    with pytest.raises(ValueError, match="resolution"):
        list(iter_review_cells(completed_eligibility_run))


def test_iter_review_cells_rejects_duplicate_or_descending_ids_across_partitions(
    completed_eligibility_run: Path, manifest_rewriter: Callable[..., None]
) -> None:
    partition_keys = _manifest(completed_eligibility_run)["expected_partition_keys"]
    manifest_rewriter(completed_eligibility_run, expected_partition_keys=partition_keys[::-1])

    with pytest.raises(ValueError, match="ascending"):
        list(iter_review_cells(completed_eligibility_run))


def test_iter_review_cells_rejects_empty_eligibility_status(
    completed_eligibility_run: Path,
) -> None:
    _replace_first_part_column(
        completed_eligibility_run,
        "eligibility_status",
        lambda statuses: ["", *statuses[1:]],
    )

    with pytest.raises(ValueError, match="eligibility_status"):
        list(iter_review_cells(completed_eligibility_run))
