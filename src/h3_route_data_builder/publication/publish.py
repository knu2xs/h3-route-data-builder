"""Validated immutable versions and atomic publication visibility."""

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import shutil
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from h3_route_data_builder.od.results import SolveOutcome
from h3_route_data_builder.publication.manifest import (
    build_dataset_manifest,
    build_partition_manifest,
    validate_manifest,
)
from h3_route_data_builder.publication.models import (
    DatasetManifest,
    LoadedPublication,
    PublicationResult,
    PublishedPart,
)
from h3_route_data_builder.publication.schema import OD_FACTS_SCHEMA
from h3_route_data_builder.publication.validation import (
    validate_parts,
    validate_publication,
)
from h3_route_data_builder.publication.write import write_table
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)
LogicalKey = tuple[int, int]
FaultHook = Callable[[str], None]


def publish_dataset(
    output_root: str | os.PathLike[str],
    dimension: pa.Table,
    facts: pa.Table,
    expected_keys: Sequence[LogicalKey],
    outcomes: Sequence[SolveOutcome],
    self_pairs: Sequence[LogicalKey],
    dataset_fingerprint: str,
    result_compatibility_fingerprint: str,
    eligibility_fingerprint: str,
    candidate_provenance: dict[str, Any],
    solve_provenance: dict[str, Any],
    *,
    prefilter_pruned_count: int = 0,
    solve_states: Mapping[LogicalKey, str] | None = None,
    fault_hook: FaultHook | None = None,
    version_id: str | None = None,
    row_group_size: int = 100_000,
    part_row_limit: int = 500_000,
) -> PublicationResult:
    """Validate, stage, and atomically expose one immutable GeoParquet version."""
    root = Path(output_root).resolve()
    versions_dir = root / "versions"
    staging_dir = root / ".staging"
    root.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    selected_version_id = version_id or _version_id(
        dataset_fingerprint,
        result_compatibility_fingerprint,
        expected_keys,
        dimension,
        facts,
        outcomes,
    )
    if Path(selected_version_id).name != selected_version_id or selected_version_id in {
        ".",
        "..",
    }:
        raise ValueError("version_id must be one safe path component")
    final_path = versions_dir / selected_version_id
    current_reference = root / "CURRENT"

    if final_path.is_dir():
        loaded = _load_version(final_path)
        if (
            loaded.dimension.to_pylist() != dimension.to_pylist()
            or loaded.facts.to_pylist() != facts.to_pylist()
            or loaded.manifest["eligibility_fingerprint"] != eligibility_fingerprint
            or loaded.manifest["candidate_provenance"] != candidate_provenance
            or loaded.manifest["solve_provenance"] != solve_provenance
            or loaded.manifest["prefilter_pruned_count"] != prefilter_pruned_count
        ):
            raise ValueError("Existing immutable version differs from requested table rows")
        _expose_current(current_reference, selected_version_id, final_path)
        return _publication_result(final_path, current_reference, loaded.manifest)

    stage_path = staging_dir / selected_version_id
    if stage_path.exists():
        shutil.rmtree(stage_path)
    stage_path.mkdir(parents=True)
    cell_part = write_table(dimension, stage_path / "solvable_cells.parquet", "solvable_cells")
    fact_parts_result = write_table(
        facts,
        stage_path / "od_facts",
        "od_facts",
        partition_by_origin=True,
        row_group_size=row_group_size,
        part_row_limit=part_row_limit,
    )
    if isinstance(fact_parts_result, PublishedPart):
        fact_parts: list[PublishedPart] = [fact_parts_result]
    else:
        fact_parts = fact_parts_result
    _write_json(
        stage_path / "reconciliation.json",
        {
            "expected_keys": [list(key) for key in sorted(expected_keys)],
            "self_pairs": [list(key) for key in sorted(self_pairs)],
            "outcomes": [outcome.to_dict() for outcome in outcomes],
            "solve_states": [
                {"logical_od_key": list(key), "state": state}
                for key, state in sorted((solve_states or {}).items())
            ],
        },
    )
    _fault(fault_hook, "after_staging")

    parts = [cell_part, *fact_parts]
    integrity_errors = validate_parts(parts)
    report = validate_publication(
        dimension,
        facts,
        expected_keys,
        outcomes,
        self_pairs,
        result_compatibility_fingerprint,
        solve_states=solve_states,
    )
    errors = [*integrity_errors, *report.errors]
    if errors:
        message = "Publication validation failed: " + "; ".join(errors)
        logger.error(message)
        raise ValueError(message)
    _fault(fault_hook, "after_validation")

    partitions = [
        build_partition_manifest("solvable_cells", [cell_part]),
        build_partition_manifest("od_facts", fact_parts),
    ]
    manifest = build_dataset_manifest(
        version_id=selected_version_id,
        dataset_fingerprint=dataset_fingerprint,
        result_compatibility_fingerprint=result_compatibility_fingerprint,
        eligibility_fingerprint=eligibility_fingerprint,
        candidate_provenance=candidate_provenance,
        solve_provenance=solve_provenance,
        expected_key_count=len(expected_keys),
        published_key_count=facts.num_rows,
        dimension_row_count=dimension.num_rows,
        outcome_counts=report.outcome_counts,
        prefilter_pruned_count=prefilter_pruned_count,
        partition_manifests=partitions,
    )
    manifest_document = manifest.to_dict(root=stage_path)
    _write_json(stage_path / "manifest.json", manifest_document)
    _fault(fault_hook, "after_manifest")

    errors = validate_manifest(manifest_document, stage_path)
    if errors:
        message = "Manifest validation failed: " + "; ".join(errors)
        logger.error(message)
        raise ValueError(message)
    manifest_checksum = _sha256_file(stage_path / "manifest.json")
    _write_json(
        stage_path / "_SUCCESS",
        {"version_id": selected_version_id, "manifest_sha256": manifest_checksum},
    )
    os.replace(stage_path, final_path)
    _expose_current(current_reference, selected_version_id, final_path)
    _fault(fault_hook, "after_exposure")
    logger.info("Published immutable GeoParquet version %s", selected_version_id)
    return _publication_result(final_path, current_reference, manifest_document)


def read_current_publication(output_root: str | os.PathLike[str]) -> LoadedPublication:
    """Read and validate the version referenced by the atomic CURRENT pointer."""
    root = Path(output_root).resolve()
    pointer = root / "CURRENT"
    if not pointer.is_file():
        raise ValueError(f"No published dataset is visible at {root}")
    try:
        reference = json.loads(pointer.read_text(encoding="utf-8"))
        version_path = root / "versions" / reference["version_id"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"Publication reference is invalid: {exc}") from exc
    loaded = _load_version(version_path)
    actual_checksum = _sha256_file(version_path / "manifest.json")
    success = json.loads((version_path / "_SUCCESS").read_text(encoding="utf-8"))
    if (
        reference.get("manifest_sha256") != actual_checksum
        or success.get("manifest_sha256") != actual_checksum
        or success.get("version_id") != loaded.version_id
    ):
        raise ValueError("Published version completion marker does not match its manifest")
    return loaded


def _load_version(version_path: Path) -> LoadedPublication:
    manifest_path = version_path / "manifest.json"
    success_path = version_path / "_SUCCESS"
    if not manifest_path.is_file() or not success_path.is_file():
        raise ValueError(f"Version is incomplete and cannot be read: {version_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        success = json.loads(success_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Version metadata is corrupt: {exc}") from exc
    errors = validate_manifest(manifest, version_path)
    if errors:
        raise ValueError("Published manifest is invalid: " + "; ".join(errors))
    if success.get("manifest_sha256") != _sha256_file(manifest_path):
        raise ValueError("Completion marker does not match the published manifest")
    part_refs: dict[str, list[PublishedPart]] = {"solvable_cells": [], "od_facts": []}
    for partition in manifest["partition_manifests"]:
        for part in partition["parts"]:
            part_refs[partition["table_name"]].append(
                PublishedPart(
                    table_name=partition["table_name"],
                    path=version_path / part["location"],
                    row_count=part["row_count"],
                    checksum=part["checksum"],
                    schema_version=part["schema_version"],
                    extent=tuple(part["extent"]) if part.get("extent") else None,
                    origin_ids=tuple(part.get("origin_ids", [])),
                )
            )
    part_errors = validate_parts([*part_refs["solvable_cells"], *part_refs["od_facts"]])
    if part_errors:
        raise ValueError("Published data parts are invalid: " + "; ".join(part_errors))
    cell_table = pq.read_table(part_refs["solvable_cells"][0].path)
    fact_tables = [pq.ParquetFile(part.path).read() for part in part_refs["od_facts"]]
    facts_table = (
        pa.concat_tables(fact_tables)
        if fact_tables
        else pa.Table.from_pylist([], schema=OD_FACTS_SCHEMA)
    )
    if not fact_tables:
        facts_table = facts_table.replace_schema_metadata(OD_FACTS_SCHEMA.metadata)
    reconciliation = json.loads((version_path / "reconciliation.json").read_text(encoding="utf-8"))
    outcomes = [SolveOutcome.from_dict(item) for item in reconciliation["outcomes"]]
    self_pairs = [tuple(key) for key in reconciliation["self_pairs"]]
    expected_keys = [tuple(key) for key in reconciliation["expected_keys"]]
    solve_states = {
        tuple(value["logical_od_key"]): value["state"]
        for value in reconciliation.get("solve_states", [])
    }
    report = validate_publication(
        cell_table,
        facts_table,
        expected_keys,
        outcomes,
        self_pairs,
        manifest["result_compatibility_fingerprint"],
        solve_states=solve_states or None,
    )
    if not report.valid:
        raise ValueError("Published logical records are invalid: " + "; ".join(report.errors))
    if cell_table.num_rows != manifest["dimension_row_count"]:
        raise ValueError("Published cell dimension row count does not match manifest")
    if facts_table.num_rows != manifest["published_key_count"]:
        raise ValueError("Published OD fact row count does not match manifest")
    if success.get("version_id") != manifest.get("version_id"):
        raise ValueError("Completion marker version does not match manifest")
    return LoadedPublication(
        version_id=manifest["version_id"],
        version_path=version_path,
        manifest=manifest,
        dimension=cell_table,
        facts=facts_table,
    )


def _expose_current(reference_path: Path, version_id: str, version_path: Path) -> None:
    checksum = _sha256_file(version_path / "manifest.json")
    success = json.loads((version_path / "_SUCCESS").read_text(encoding="utf-8"))
    if success.get("manifest_sha256") != checksum:
        raise ValueError("Cannot expose a version with an invalid completion marker")
    temporary = reference_path.with_name(f".{reference_path.name}.{os.getpid()}.tmp")
    _write_json(
        temporary,
        {"version_id": version_id, "manifest_sha256": checksum},
    )
    os.replace(temporary, reference_path)


def _publication_result(
    version_path: Path,
    current_reference: Path,
    manifest_document: dict[str, Any],
) -> PublicationResult:
    return PublicationResult(
        version_id=manifest_document["version_id"],
        version_path=version_path,
        manifest_path=version_path / "manifest.json",
        success_path=version_path / "_SUCCESS",
        current_reference=current_reference,
        manifest=_manifest_from_document(manifest_document),
    )


def _manifest_from_document(document: dict[str, Any]) -> DatasetManifest:
    from h3_route_data_builder.publication.models import (
        DatasetManifest,
        PartitionManifest,
    )

    partitions = []
    for raw_partition in document["partition_manifests"]:
        parts = tuple(
            PublishedPart(
                table_name=raw_partition["table_name"],
                path=Path(part["location"]),
                row_count=part["row_count"],
                checksum=part["checksum"],
                schema_version=part["schema_version"],
                extent=tuple(part["extent"]) if part.get("extent") else None,
                origin_ids=tuple(part.get("origin_ids", [])),
            )
            for part in raw_partition["parts"]
        )
        partitions.append(
            PartitionManifest(
                table_name=raw_partition["table_name"],
                partition_keys=tuple(raw_partition["partition_keys"]),
                parts=parts,
                row_count=raw_partition["row_count"],
                schema_version=raw_partition["schema_version"],
                extent=(tuple(raw_partition["extent"]) if raw_partition.get("extent") else None),
            )
        )
    return DatasetManifest(
        version_id=document["version_id"],
        status=document["status"],
        dataset_fingerprint=document["dataset_fingerprint"],
        result_compatibility_fingerprint=document["result_compatibility_fingerprint"],
        eligibility_fingerprint=document["eligibility_fingerprint"],
        candidate_provenance=document["candidate_provenance"],
        solve_provenance=document["solve_provenance"],
        expected_key_count=document["expected_key_count"],
        published_key_count=document["published_key_count"],
        dimension_row_count=document["dimension_row_count"],
        outcome_counts=document["outcome_counts"],
        prefilter_pruned_count=document["prefilter_pruned_count"],
        partition_manifests=tuple(partitions),
        created_at=document["created_at"],
        schema_versions=document["schema_versions"],
        geoparquet_version=document["geoparquet_version"],
        crs=document["crs"],
        partition_scheme=document["partition_scheme"],
        spatial_ordering_policy=document["spatial_ordering_policy"],
    )


def _version_id(
    dataset_fingerprint: str,
    result_fingerprint: str,
    expected_keys: Sequence[LogicalKey],
    dimension: pa.Table,
    facts: pa.Table,
    outcomes: Sequence[SolveOutcome],
) -> str:
    digest = hashlib.sha256()
    identities = {
        "dataset_fingerprint": dataset_fingerprint,
        "result_fingerprint": result_fingerprint,
        "expected_keys": sorted([list(key) for key in expected_keys]),
        "outcomes": [
            outcome.to_dict() for outcome in sorted(outcomes, key=lambda item: item.logical_od_key)
        ],
    }
    digest.update(
        json.dumps(
            identities,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
    _update_table_digest(digest, dimension)
    _update_table_digest(digest, facts)
    return f"v-{digest.hexdigest()[:24]}"


def _update_table_digest(digest: Any, table: pa.Table) -> None:
    """Hash Arrow rows in bounded record batches for deterministic version identity."""
    digest.update(json.dumps(table.schema.names, separators=(",", ":")).encode("utf-8"))
    for batch in table.to_batches(max_chunksize=4096):
        for row in batch.to_pylist():
            normalized = {
                key: value.hex() if isinstance(value, bytes) else value
                for key, value in row.items()
            }
            digest.update(
                json.dumps(
                    normalized,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
            digest.update(b"\n")


def _fault(fault_hook: FaultHook | None, phase: str) -> None:
    if fault_hook is not None:
        fault_hook(phase)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
