"""File integrity, GeoParquet, and logical-key reconciliation validation."""

import hashlib
import json
import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping, Sequence
from pathlib import Path

import duckdb
from h3.api import basic_int as h3
from h3_route_data_builder.eligibility.cells import canonical_h3_ids
import pyarrow as pa
import pyarrow.parquet as pq

from h3_route_data_builder.od.results import OutcomeClass, SolveOutcome
from h3_route_data_builder.publication.models import PublishedPart, ValidationReport
from h3_route_data_builder.publication.schema import (
    GEOPARQUET_VERSION,
    OD_FACTS_SCHEMA,
    SOLVABLE_CELLS_SCHEMA,
)

LogicalKey = tuple[int, int]


def validate_parts(parts: Sequence[PublishedPart], max_workers: int = 2) -> tuple[str, ...]:
    """Validate immutable parts serially or with bounded independent checks.

    Concurrent results are flattened in input order so diagnostics remain deterministic.
    """
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or not 1 <= max_workers <= 2
    ):
        raise ValueError("max_workers must be 1 or 2")
    if max_workers == 1 or len(parts) < 2:
        return tuple(error for part in parts for error in _validate_part(part))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        per_part_errors = executor.map(_validate_part, parts)
        return tuple(error for errors in per_part_errors for error in errors)


def _validate_part(part: PublishedPart) -> tuple[str, ...]:
    errors: list[str] = []
    if not part.path.is_file():
        return (f"Missing part file: {part.path}",)
    if _sha256_file(part.path) != part.checksum:
        return (f"Part checksum mismatch: {part.path}",)
    try:
        parquet = pq.ParquetFile(part.path)
        if parquet.metadata.num_rows != part.row_count:
            errors.append(f"Part row count mismatch: {part.path}")
        expected = SOLVABLE_CELLS_SCHEMA if part.table_name == "solvable_cells" else OD_FACTS_SCHEMA
        if not parquet.schema_arrow.remove_metadata().equals(expected.remove_metadata()):
            errors.append(f"Part schema mismatch: {part.path}")
        if (parquet.schema_arrow.metadata or {}).get(b"schema_version") != expected.metadata[
            b"schema_version"
        ] or part.schema_version.encode() != expected.metadata[b"schema_version"]:
            errors.append(f"Part schema version mismatch: {part.path}")
        if part.table_name == "od_facts":
            actual_origins = set(
                parquet.read(columns=["origin_h3_id"]).column("origin_h3_id").to_pylist()
            )
            if actual_origins != set(part.origin_ids):
                errors.append(f"Part origin metadata mismatch: {part.path}")
        if part.table_name == "solvable_cells":
            geo_metadata = _validate_geo_metadata(
                parquet.schema_arrow.metadata or {},
                require_bbox=part.row_count > 0,
            )
            if part.row_count > 0:
                errors.extend(_validate_file_extents(part.path, geo_metadata))
    except (duckdb.Error, OSError, ValueError, pa.ArrowException) as exc:
        errors.append(f"Cannot validate part {part.path}: {exc}")
    return tuple(errors)


def validate_publication(
    dimension: pa.Table,
    facts: pa.Table,
    expected_keys: Sequence[LogicalKey],
    outcomes: Sequence[SolveOutcome],
    self_pairs: Sequence[LogicalKey],
    build_fingerprint: str,
    solve_states: Mapping[LogicalKey, str] | None = None,
) -> ValidationReport:
    """Validate canonical tables against expected logical keys and authoritative outcomes."""
    errors: list[str] = []
    if not dimension.schema.remove_metadata().equals(SOLVABLE_CELLS_SCHEMA.remove_metadata()):
        errors.append("Solvable-cell dimension schema is incompatible")
    if not facts.schema.remove_metadata().equals(OD_FACTS_SCHEMA.remove_metadata()):
        errors.append("OD facts schema is incompatible")
    for table, schema in ((dimension, SOLVABLE_CELLS_SCHEMA), (facts, OD_FACTS_SCHEMA)):
        if (table.schema.metadata or {}).get(b"schema_version") != schema.metadata[
            b"schema_version"
        ]:
            errors.append("Publication table has an incompatible integer schema version")
    try:
        _validate_geo_metadata(dimension.schema.metadata or {}, require_bbox=False)
    except ValueError as exc:
        errors.append(str(exc))

    cell_rows = dimension.to_pylist()
    cell_ids = [row["h3_id"] for row in cell_rows]
    if len(set(cell_ids)) != len(cell_ids):
        errors.append("Solvable-cell dimension contains duplicate H3 identifiers")
    cell_id_set = set(cell_ids)
    for row in cell_rows:
        try:
            canonical_h3_ids((row["h3_id"],))
            if (
                type(row["resolution"]) is not int
                or h3.get_resolution(row["h3_id"]) != row["resolution"]
            ):
                errors.append(f"Cell identifier is not canonical at its resolution: {row['h3_id']}")
        except (TypeError, ValueError):
            errors.append(f"Invalid H3 identifier in cell dimension: {row['h3_id']}")
        if row["eligibility_status"] != "solvable":
            errors.append(f"Cell {row['h3_id']} is not solvable")
        if any(
            row[column] is None
            for column in (
                "cell_geometry",
                "centroid_geometry",
                "representative_geometry",
            )
        ):
            errors.append(f"Cell {row['h3_id']} has missing geometry")

    expected_counts = Counter(expected_keys)
    expected_set = set(expected_keys)
    if any(count > 1 for count in expected_counts.values()):
        errors.append("Expected logical OD keys contain duplicates")
    for key in expected_set:
        try:
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError("Expected key must be an ordered integer pair")
            canonical_h3_ids(key)
        except ValueError:
            errors.append(f"Invalid expected logical OD key: {key}")
            continue
        if key[0] not in cell_id_set or key[1] not in cell_id_set:
            errors.append(f"Expected OD key endpoint is absent from the dimension: {key}")
    outcome_counts = Counter()
    outcome_by_key: dict[LogicalKey, SolveOutcome] = {}
    for outcome in outcomes:
        if outcome.logical_od_key in outcome_by_key:
            errors.append(f"Duplicate solve outcome for {outcome.logical_od_key}")
        outcome_by_key[outcome.logical_od_key] = outcome
        outcome_counts[outcome.classification.value] += 1
        if outcome.classification in {
            OutcomeClass.QUALIFYING,
            OutcomeClass.CUTOFF_EXCLUDED,
        }:
            if (
                outcome.actual_cost is None
                or not math.isfinite(outcome.actual_cost)
                or outcome.actual_cost < 0
                or not outcome.cost_unit
            ):
                errors.append(
                    f"Route outcome has invalid actual-cost evidence: {outcome.logical_od_key}"
                )
        elif outcome.actual_cost is not None or outcome.cost_unit is not None:
            errors.append(f"Non-route outcome contains route cost: {outcome.logical_od_key}")
    self_key_counts = Counter(self_pairs)
    if any(origin != destination for origin, destination in self_pairs):
        errors.append("Self-pair keys must have identical endpoints")
    if any(count > 1 for count in self_key_counts.values()):
        errors.append("Self-pair keys contain duplicates")
    expected_self_keys = {key for key in expected_set if key[0] == key[1]}
    if set(self_pairs) != expected_self_keys:
        errors.append("Self-pair records do not exactly match expected self keys")

    facts_rows = facts.to_pylist()
    fact_keys = [(row["origin_h3_id"], row["destination_h3_id"]) for row in facts_rows]
    fact_counts = Counter(fact_keys)
    if any(count > 1 for count in fact_counts.values()):
        errors.append("OD facts contain duplicate directed logical keys")
    for row, key in zip(facts_rows, fact_keys):
        if key[0] not in cell_id_set or key[1] not in cell_id_set:
            errors.append(f"OD fact endpoint is absent from the solvable-cell dimension: {key}")
        if row["build_fingerprint"] != build_fingerprint:
            errors.append(f"OD fact has an incompatible build fingerprint: {key}")
        matching_outcome = outcome_by_key.get(key)
        if (
            matching_outcome is not None
            and matching_outcome.classification is OutcomeClass.QUALIFYING
        ):
            unit = (matching_outcome.cost_unit or "").casefold()
            if unit in {"m", "meter", "meters", "metre", "metres"}:
                cost_field = "network_distance_m"
            elif unit in {"s", "sec", "second", "seconds"}:
                cost_field = "network_time_s"
            else:
                cost_field = ""
                errors.append(f"Committed outcome has an unsupported cost unit: {key}")
            if cost_field and row[cost_field] != matching_outcome.actual_cost:
                errors.append(f"OD fact cost does not match its committed outcome: {key}")
            if not row["work_item_id"]:
                errors.append(f"Non-self OD fact has no work_item_id: {key}")

    outcome_keys = set(outcome_by_key)
    if outcome_keys - expected_set:
        errors.append(f"Unexpected solve outcomes: {sorted(outcome_keys - expected_set)}")
    if set(fact_keys) - expected_set:
        errors.append(f"Unexpected OD facts: {sorted(set(fact_keys) - expected_set)}")
    if set(self_pairs) - expected_set:
        errors.append("Self-pairs include keys outside the expected set")
    if solve_states is not None:
        for key in expected_set - set(self_pairs):
            if solve_states.get(key) != "committed":
                errors.append(
                    f"Expected key {key} is not committed (state={solve_states.get(key)!r})"
                )

    expected_fact_keys: set[LogicalKey] = set(self_pairs)
    expected_outcome_keys = expected_set - set(self_pairs)
    for key in expected_outcome_keys:
        outcome = outcome_by_key.get(key)
        if outcome is None:
            errors.append(f"Missing authoritative outcome for expected key {key}")
            continue
        classification = outcome.classification
        if classification is OutcomeClass.QUALIFYING:
            expected_fact_keys.add(key)
        elif classification not in {
            OutcomeClass.UNLOCATED,
            OutcomeClass.UNREACHABLE,
            OutcomeClass.CUTOFF_EXCLUDED,
        }:
            errors.append(f"Unresolved publication outcome for {key}: {classification}")
    if outcome_keys & set(self_pairs):
        errors.append("Self-pairs must not have Feature 003 solve outcomes")
    if set(fact_keys) != expected_fact_keys:
        errors.append(
            f"Published fact keys do not match qualifying outcomes and self-pairs "
            f"(missing={sorted(expected_fact_keys - set(fact_keys))}, "
            f"extra={sorted(set(fact_keys) - expected_fact_keys)})"
        )
    for row in facts_rows:
        if row["solve_status"] == "self_pair":
            if row["work_item_id"] is not None:
                errors.append("Self-pair fact must have a null work_item_id")
            if row["network_distance_m"] != 0.0 or row["network_time_s"] != 0.0:
                errors.append("Self-pair fact must have zero costs")
        elif row["solve_status"] != "solved" or not row["work_item_id"]:
            errors.append("Non-self fact must be solved and include a work_item_id")
        if row["network_distance_m"] is None and row["network_time_s"] is None:
            errors.append("OD fact must contain at least one actual network cost")
        for name in ("network_distance_m", "network_time_s"):
            value = row[name]
            if value is not None and (not math.isfinite(value) or value < 0):
                errors.append(f"OD fact has an invalid {name} value")
    outcome_counts["self_pair"] += len(self_pairs)
    return ValidationReport(not errors, tuple(errors), dict(sorted(outcome_counts.items())))


def _validate_geo_metadata(
    metadata: dict[bytes, bytes], require_bbox: bool
) -> dict[str, list[float]]:
    raw = metadata.get(b"geo")
    if raw is None:
        raise ValueError("GeoParquet metadata is missing")
    try:
        geo = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"GeoParquet metadata is invalid JSON: {exc}") from exc
    if geo.get("version") != GEOPARQUET_VERSION:
        raise ValueError("GeoParquet version is not 1.1.0")
    if geo.get("primary_column") != "cell_geometry":
        raise ValueError("GeoParquet primary geometry column must be cell_geometry")
    columns = geo.get("columns", {})
    required_columns = {
        "cell_geometry",
        "centroid_geometry",
        "representative_geometry",
    }
    if set(columns) != required_columns:
        raise ValueError("GeoParquet metadata must describe all three geometry columns")
    extents: dict[str, list[float]] = {}
    for name, geometry_type in (
        ("cell_geometry", "Polygon"),
        ("centroid_geometry", "Point"),
        ("representative_geometry", "Point"),
    ):
        definition = columns.get(name, {})
        crs = definition.get("crs", {})
        bbox = definition.get("bbox")
        if definition.get("encoding") != "WKB":
            raise ValueError(f"GeoParquet geometry {name} must use WKB")
        if geometry_type not in definition.get("geometry_types", []):
            raise ValueError(f"GeoParquet geometry {name} has an incompatible type")
        if (
            crs.get("id") != {"authority": "EPSG", "code": 4326}
            or crs.get("type") != "GeographicCRS"
            or not crs.get("datum_ensemble")
            or not crs.get("coordinate_system")
        ):
            raise ValueError(f"GeoParquet geometry {name} must use EPSG:4326 PROJJSON")
        if require_bbox and (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                not isinstance(value, (float, int)) or not math.isfinite(value) for value in bbox
            )
        ):
            raise ValueError(f"GeoParquet geometry {name} has no usable bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            if bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                raise ValueError(f"GeoParquet geometry {name} bbox is inverted")
            extents[name] = [float(value) for value in bbox]
    return extents


def _validate_file_extents(path: Path, metadata_extents: dict[str, list[float]]) -> list[str]:
    """Compare advertised GeoParquet bboxes with geometry-derived DuckDB extents."""
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        errors: list[str] = []
        for column_name, expected in metadata_extents.items():
            values = connection.execute(
                "SELECT ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent) "
                f"FROM (SELECT ST_Extent({column_name}) AS extent "
                "FROM read_parquet(?))",
                [str(path)],
            ).fetchone()
            if values is None or any(value is None for value in values):
                errors.append(f"GeoParquet geometry {column_name} has no readable extent")
                continue
            actual = [float(value) for value in values]
            if any(
                abs(actual_value - expected_value) > 1e-9
                for actual_value, expected_value in zip(actual, expected)
            ):
                errors.append(f"GeoParquet geometry {column_name} bbox does not match data")
        return errors
    finally:
        connection.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
