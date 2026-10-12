"""Serial ArcPy workflow for building audited H3 eligibility results."""

import hashlib
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import arcpy
import h3

from h3_route_data_builder.config import config
from h3_route_data_builder.eligibility.cells import canonical_h3_ids
from h3_route_data_builder.eligibility.config import (
    EligibilityConfig,
    eligibility_config_from_node,
)
from h3_route_data_builder.eligibility.engine import (
    build_cell_eligibility_result,
    build_geometry_candidates,
)
from h3_route_data_builder.eligibility.fingerprint import build_input_fingerprint
from h3_route_data_builder.eligibility.limits import (
    EXECUTION_LIMIT_POLICY_VERSION,
    ExecutionLimits,
    resolve_execution_limits,
)
from h3_route_data_builder.eligibility.models import (
    EligibilityRunState,
    PartitionStatus,
    RunStatus,
)
from h3_route_data_builder.eligibility.output import eligibility_results_to_table
from h3_route_data_builder.eligibility.reconcile import finalize_eligibility_results
from h3_route_data_builder.eligibility.run_state import (
    create_run_state,
    finalize_run,
    load_run_state,
    save_run_state,
    transition_partition,
)
from h3_route_data_builder.eligibility.staging import (
    StagedPart,
    read_verified_staged_part,
    stage_table_batches,
)
from h3_route_data_builder.network.eligibility import (
    EdgeEligibilityDecision,
    NetworkDatasetMetadata,
    NetworkEdgeRecord,
    classify_edge_directions,
    iter_network_edges,
    load_network_metadata,
)
from h3_route_data_builder.network.geometry import (
    WGS84_CRS_NAME,
    candidate_h3_cells_for_aoi,
    cell_result_geometries_wkb,
    h3_cell_polygon,
    project_geometry,
    validate_aoi_geometry,
)
from h3_route_data_builder.network.locations import (
    locate_representative_candidates_by_cell,
)
from h3_route_data_builder.network.representatives import rank_representative_candidates
from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)


@dataclass(frozen=True)
class EligibilityBuildSummary:
    """Summary of a reconciled eligibility build."""

    run_id: str
    run_directory: Path
    run_status: str
    expected_partition_count: int
    reconciled_partition_count: int
    cell_result_count: int
    solvable_cell_count: int
    staged_part_count: int


def run_geometry_eligibility(
    aoi_feature_path: str,
    network_dataset_path: str,
    output_directory: str | os.PathLike[str],
    config_node: Any = config,
    *,
    batch_size: int | None = None,
    part_row_limit: int | None = None,
    total_output_hard_cap: int | None = None,
) -> EligibilityBuildSummary:
    """Build and reconcile geometry eligibility with optional resource-aware limits.

    Args:
        aoi_feature_path: Polygon feature class or layer containing the AOI.
        network_dataset_path: Network dataset to inspect and query read-only.
        output_directory: Destination root for this run's staging directory and manifest.
        config_node: Resolved project configuration.
        batch_size: Optional explicit source-batch override; otherwise inferred.
        part_row_limit: Optional explicit staged-part override; otherwise inferred.
        total_output_hard_cap: Optional explicit solvable-cell cap; otherwise inferred.

    Returns:
        Summary of the completed run and its staged output location.

    Raises:
        ValueError: If inputs/configuration are invalid or the total cap is exceeded.
        RuntimeError: If ArcPy, Network Analyst, staging, or reconciliation fails.
    """
    settings = eligibility_config_from_node(config_node)
    if not arcpy.Exists(aoi_feature_path):
        raise ValueError(f"ArcPy cannot resolve AOI feature input: {aoi_feature_path}")

    aoi_source_geometry = _read_and_union_aoi(aoi_feature_path)
    source_spatial_reference = validate_aoi_geometry(aoi_source_geometry)
    output_spatial_reference = arcpy.SpatialReference(WGS84_CRS_NAME)
    aoi_wgs84 = project_geometry(aoi_source_geometry, output_spatial_reference)
    network_metadata = load_network_metadata(network_dataset_path)
    if settings.travel_mode not in network_metadata.travel_modes:
        raise ValueError(
            f"Travel mode '{settings.travel_mode}' is not available in the network dataset"
        )
    mode_restrictions = tuple(
        sorted(
            network_metadata.travel_modes[settings.travel_mode].get(
                "restrictionAttributeNames", []
            )
        )
    )
    if settings.restrictions != mode_restrictions:
        raise ValueError(
            "network.restrictions must match the selected travel mode's restrictionAttributeNames"
        )

    candidate_ids = canonical_h3_ids(
        candidate_h3_cells_for_aoi(aoi_wgs84, settings.h3_resolution)
    )
    network_fingerprint = _network_metadata_fingerprint(network_metadata)
    aoi_fingerprint = hashlib.sha256(
        bytes(aoi_source_geometry.WKB)
        + source_spatial_reference.exportToString().encode("utf-8")
    ).hexdigest()
    software_versions = {
        "python": platform.python_version(),
        "arcgis_pro": str(arcpy.GetInstallInfo().get("Version", "unknown")),
        "h3": str(getattr(h3, "__version__", "unknown")),
        "package": "0.0.0",
    }
    input_identity_fingerprint = build_input_fingerprint(
        aoi_fingerprint=aoi_fingerprint,
        network_fingerprint=network_fingerprint,
        travel_mode=settings.travel_mode,
        restrictions=settings.restrictions,
        h3_resolution=settings.h3_resolution,
        eligibility_policy=_policy_payload(settings),
        schema_version="1",
        software_versions=software_versions,
    )
    run_directory = Path(output_directory) / (
        f"eligibility-{input_identity_fingerprint[:20]}"
    )
    run_directory.mkdir(parents=True, exist_ok=True)
    state_path = run_directory / "run-state.json"
    manifest_path = run_directory / "run-manifest.json"

    if state_path.exists():
        run_state = load_run_state(state_path)
        manifest = _read_manifest(manifest_path, input_identity_fingerprint)
        saved_limits = ExecutionLimits.from_manifest(manifest["execution_limits"])
    else:
        run_state = None
        manifest = None
        saved_limits = None

    execution_limits = resolve_execution_limits(
        output_directory,
        batch_size,
        part_row_limit,
        total_output_hard_cap,
        saved_limits,
        candidate_count=len(candidate_ids),
    )
    if saved_limits is not None:
        if manifest is None:
            raise RuntimeError("Saved execution limits have no corresponding manifest")
        if execution_limits.to_manifest() != manifest["execution_limits"]:
            raise ValueError("Explicit execution limits differ from the existing run")

    for limit_name in ("batch_size", "part_row_limit", "total_output_hard_cap"):
        logger.info(
            "Execution limit %s=%s (%s%s)",
            limit_name,
            getattr(execution_limits, limit_name),
            getattr(execution_limits, f"{limit_name}_source"),
            "; reused from existing run" if manifest is not None else "",
        )
    logger.info(
        "Execution limit inference policy version %s", EXECUTION_LIMIT_POLICY_VERSION
    )
    if execution_limits.resource_snapshot is not None:
        logger.info(
            "Limit inference resources: available memory=%s bytes, output-volume free=%s bytes",
            execution_limits.resource_snapshot.available_memory_bytes,
            execution_limits.resource_snapshot.available_disk_bytes,
        )

    fingerprint = build_input_fingerprint(
        aoi_fingerprint=aoi_fingerprint,
        network_fingerprint=network_fingerprint,
        travel_mode=settings.travel_mode,
        restrictions=settings.restrictions,
        h3_resolution=settings.h3_resolution,
        eligibility_policy={
            **_policy_payload(settings),
            "execution_limits": execution_limits.to_manifest(),
        },
        schema_version="1",
        software_versions=software_versions,
    )
    run_id = fingerprint[:20]
    partition_keys = [
        f"partition-{batch_index:06d}"
        for batch_index in range(
            (len(candidate_ids) + execution_limits.batch_size - 1)
            // execution_limits.batch_size
        )
    ]

    if run_state is not None:
        if manifest is None:
            raise RuntimeError("Existing run state has no manifest")
        if run_state.run_id != run_id or run_state.expected_partition_keys != tuple(
            partition_keys
        ):
            raise ValueError(
                "Existing run state does not match this AOI/network/configuration"
            )
        if manifest.get("build_fingerprint") != fingerprint:
            raise ValueError("Existing run manifest fingerprint does not match limits")
        if manifest.get("expected_partition_keys") != partition_keys:
            raise ValueError("Existing run manifest has different expected partitions")
        if run_state.status == RunStatus.COMPLETE:
            return _build_summary(run_state, run_directory, manifest_path)
        if run_state.status == RunStatus.FAILED_INCOMPLETE:
            raise ValueError(
                "This eligibility run previously failed and is not resumable"
            )
    else:
        run_state = create_run_state(
            run_id,
            partition_keys,
            execution_limits.total_output_hard_cap,
        )
        manifest = {
            "run_id": run_id,
            "run_directory": str(run_directory),
            "build_fingerprint": fingerprint,
            "input_fingerprint": {
                "aoi": aoi_fingerprint,
                "network": network_fingerprint,
                "identity": input_identity_fingerprint,
            },
            "software_versions": software_versions,
            "policy": _policy_payload(settings),
            "execution_limits": execution_limits.to_manifest(),
            "output_crs_wkt": output_spatial_reference.exportToString(),
            "expected_partition_keys": partition_keys,
            "parts": [],
            "partition_summaries": {},
            "cell_result_count": 0,
            "solvable_cell_count": 0,
            "run_status": run_state.status.value,
        }
        save_run_state(state_path, run_state)
        _write_json_atomic(manifest_path, manifest)

    if run_state is None or manifest is None:
        raise RuntimeError(
            "Run state and manifest must be initialized before processing"
        )

    all_result_count = 0
    solvable_count = 0
    part_count = len(manifest.get("parts", []))
    try:
        for batch_index, start in enumerate(
            range(0, len(candidate_ids), execution_limits.batch_size)
        ):
            partition_key = f"partition-{batch_index:06d}"
            current_status = run_state.partition_status[partition_key]
            if current_status == PartitionStatus.RECONCILED:
                summary = manifest.get("partition_summaries", {}).get(partition_key)
                if summary is None:
                    raise ValueError(
                        f"Missing run summary for reconciled partition {partition_key}"
                    )
                all_result_count += int(summary["cell_result_count"])
                solvable_count += int(summary["solvable_cell_count"])
                continue
            if current_status == PartitionStatus.STAGED:
                _verify_partition_parts(manifest, partition_key)
                transition_partition(
                    run_state, partition_key, PartitionStatus.RECONCILED
                )
                save_run_state(state_path, run_state)
                summary = manifest.get("partition_summaries", {}).get(partition_key)
                if summary is None:
                    raise ValueError(
                        f"Missing run summary for staged partition {partition_key}"
                    )
                all_result_count += int(summary["cell_result_count"])
                solvable_count += int(summary["solvable_cell_count"])
                continue
            if current_status in {PartitionStatus.PENDING, PartitionStatus.FAILED}:
                transition_partition(
                    run_state, partition_key, PartitionStatus.PROCESSING
                )
                save_run_state(state_path, run_state)

            batch_ids = candidate_ids[start : start + execution_limits.batch_size]
            cell_geometries = {
                cell_id: h3_cell_polygon(
                    cell_id,
                )
                for cell_id in batch_ids
            }
            batch_aoi_filter = _union_geometries(cell_geometries.values())
            edge_read_started = perf_counter()
            edges = list(
                iter_network_edges(
                    network_dataset_path,
                    settings.travel_mode,
                    batch_aoi_filter,
                    defer_eligibility=True,
                    metadata=network_metadata,
                )
            )
            logger.info(
                "Read %s spatially filtered network edges for %s cells in %s (%.2f seconds)",
                len(edges),
                len(batch_ids),
                partition_key,
                perf_counter() - edge_read_started,
            )

            def classify_intersecting_edge(
                edge: NetworkEdgeRecord,
            ) -> EdgeEligibilityDecision:
                return classify_edge_directions(
                    edge.source_name,
                    edge.evaluator_fields,
                    network_metadata.attributes,
                    network_metadata.travel_modes[settings.travel_mode],
                )

            geometry_started = perf_counter()
            geometry_candidates = build_geometry_candidates(
                cell_geometries,
                edges,
                aoi_wgs84,
                settings.h3_resolution,
                edge_classifier=classify_intersecting_edge,
            )
            logger.info(
                "Built geometry evidence for %s in %.2f seconds",
                partition_key,
                perf_counter() - geometry_started,
            )

            policy_evidence = _policy_payload(settings)
            policy_evidence["output_crs"] = output_spatial_reference.name
            policy_evidence["execution_limits"] = execution_limits.to_manifest()
            representative_candidates_by_cell = {}
            for candidate in geometry_candidates:
                representative_candidates_by_cell[candidate.h3_id_hex] = (
                    rank_representative_candidates(
                        candidate.h3_id_hex,
                        candidate.centroid_geometry,
                        candidate.intersecting_edges,
                        settings.representative_snap_tolerance_m,
                    )
                )
            location_started = perf_counter()
            representatives = locate_representative_candidates_by_cell(
                representative_candidates_by_cell,
                network_dataset_path,
                settings.travel_mode,
                settings.representative_snap_tolerance_m,
            )
            logger.info(
                "Located %s representative candidates for %s cells in %.2f seconds",
                sum(
                    len(candidates)
                    for candidates in representative_candidates_by_cell.values()
                ),
                len(representative_candidates_by_cell),
                perf_counter() - location_started,
            )
            results = []
            for candidate in geometry_candidates:
                results.append(
                    build_cell_eligibility_result(
                        candidate,
                        representatives.get(candidate.h3_id_hex),
                        settings.representative_snap_tolerance_m,
                        policy_evidence,
                        fingerprint,
                    )
                )

            geometry_wkb = cell_result_geometries_wkb(
                results,
            )
            output_table = eligibility_results_to_table(results, geometry_wkb)
            staged_parts = stage_table_batches(
                output_table,
                run_directory / "parts" / partition_key,
                partition_key,
                execution_limits.batch_size,
                execution_limits.part_row_limit,
            )
            part_entries = [
                {
                    "partition_key": partition_key,
                    "part_key": staged.part_key,
                    "path": staged.path.relative_to(run_directory).as_posix(),
                    "row_count": staged.row_count,
                    "checksum": staged.checksum,
                }
                for staged in staged_parts
            ]
            manifest["parts"] = [
                part
                for part in manifest["parts"]
                if part["partition_key"] != partition_key
            ] + part_entries
            batch_solvable_count = sum(
                result.eligibility_status.value == "solvable" for result in results
            )
            manifest["partition_summaries"][partition_key] = {
                "cell_result_count": len(results),
                "solvable_cell_count": batch_solvable_count,
            }
            all_result_count += len(results)
            solvable_count += batch_solvable_count
            manifest["cell_result_count"] = sum(
                int(summary["cell_result_count"])
                for summary in manifest["partition_summaries"].values()
            )
            manifest["solvable_cell_count"] = sum(
                int(summary["solvable_cell_count"])
                for summary in manifest["partition_summaries"].values()
            )
            transition_partition(run_state, partition_key, PartitionStatus.STAGED)
            manifest["run_status"] = run_state.status.value
            _write_json_atomic(manifest_path, manifest)
            transition_partition(run_state, partition_key, PartitionStatus.RECONCILED)
            save_run_state(state_path, run_state)
            part_count += len(staged_parts)

            if solvable_count > execution_limits.total_output_hard_cap:
                run_state.status = RunStatus.FAILED_INCOMPLETE
                run_state.unique_solvable_cell_count = solvable_count
                manifest["run_status"] = run_state.status.value
                manifest["failure_reason"] = "total output hard cap exceeded"
                save_run_state(state_path, run_state)
                _write_json_atomic(manifest_path, manifest)
                raise ValueError(
                    "Unique solvable H3 cell count exceeds total output hard cap"
                )

        finalize_run(run_state, solvable_count)
        save_run_state(state_path, run_state)
        manifest["run_status"] = run_state.status.value
        _write_json_atomic(manifest_path, manifest)
        if run_state.status != RunStatus.COMPLETE:
            raise ValueError("Eligibility run did not reach complete state")
    except Exception as exc:
        if run_state.status == RunStatus.PROCESSING:
            failed_partition = locals().get("partition_key")
            if (
                failed_partition in run_state.partition_status
                and run_state.partition_status[failed_partition]
                in {PartitionStatus.PROCESSING, PartitionStatus.STAGED}
            ):
                transition_partition(
                    run_state, failed_partition, PartitionStatus.FAILED
                )
            save_run_state(state_path, run_state)
        manifest["run_status"] = run_state.status.value
        manifest["failure_reason"] = str(exc)
        _write_json_atomic(manifest_path, manifest)
        message = f"Eligibility run {run_id} failed: {exc}"
        logger.error(message)
        raise

    logger.info(
        "Eligibility run %s completed: %s cells, %s solvable, %s parts",
        run_id,
        all_result_count,
        solvable_count,
        part_count,
    )
    return EligibilityBuildSummary(
        run_id=run_id,
        run_directory=run_directory,
        run_status=run_state.status.value,
        expected_partition_count=len(partition_keys),
        reconciled_partition_count=sum(
            status == PartitionStatus.RECONCILED
            for status in run_state.partition_status.values()
        ),
        cell_result_count=int(manifest["cell_result_count"]),
        solvable_cell_count=int(manifest["solvable_cell_count"]),
        staged_part_count=len(manifest["parts"]),
    )


def _read_manifest(
    manifest_path: Path,
    input_identity_fingerprint: str,
) -> dict[str, Any]:
    """Read a manifest and validate the stable input identity for resumption."""
    if not manifest_path.is_file():
        raise ValueError(f"Run state exists without a manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("input_fingerprint", {}).get("identity")
        != input_identity_fingerprint
    ):
        raise ValueError("Existing run manifest does not match current inputs")
    return manifest


def _read_and_union_aoi(aoi_feature_path: str) -> arcpy.Geometry:
    """Read and union AOI polygon rows without changing the source feature class."""
    description = arcpy.Describe(aoi_feature_path)
    if description.shapeType.casefold() != "polygon":
        raise ValueError("AOI input must be polygon geometry")
    source_reference = description.spatialReference
    if source_reference is None or source_reference.name == "Unknown":
        raise ValueError("AOI input has an unknown spatial reference")
    combined_geometry = None
    try:
        with arcpy.da.SearchCursor(aoi_feature_path, ["SHAPE@"]) as cursor:
            for (geometry,) in cursor:
                if geometry is None or geometry.pointCount == 0:
                    continue
                if geometry.spatialReference != source_reference:
                    raise ValueError(
                        "AOI rows do not share the input spatial reference"
                    )
                combined_geometry = (
                    geometry
                    if combined_geometry is None
                    else combined_geometry.union(geometry)
                )
    except arcpy.ExecuteError as exc:
        message = f"Could not read AOI geometry from '{aoi_feature_path}': {arcpy.GetMessages(2)}"
        logger.error(message)
        raise RuntimeError(message) from exc
    if combined_geometry is None:
        raise ValueError("AOI input contains no non-empty polygon geometry")
    return combined_geometry


def _union_geometries(geometries: Any) -> arcpy.Geometry:
    """Union a non-empty sequence of WGS84 geometries."""
    iterator = iter(geometries)
    try:
        combined = next(iterator)
    except StopIteration as exc:
        raise ValueError("Cannot union an empty geometry sequence") from exc
    for geometry in iterator:
        combined = combined.union(geometry)
    return combined


def _network_metadata_fingerprint(metadata: NetworkDatasetMetadata) -> str:
    """Fingerprint network source paths, schemas, evaluator definitions, and travel modes."""
    source_metadata: list[dict[str, Any]] = []
    for source in metadata.edge_sources:
        fields = [
            {"name": field.name, "type": field.type}
            for field in arcpy.ListFields(source.feature_class_path)
        ]
        source_metadata.append(
            {
                "name": source.name,
                "source_id": source.source_id,
                "path": source.feature_class_path,
                "fields": fields,
            }
        )
    attribute_metadata = {
        name: {
            "usage_type": attribute.usage_type,
            "default_edge_evaluator_type": attribute.default_edge_evaluator_type,
            "default_edge_data": attribute.default_edge_data,
            "evaluators": [
                {
                    "source_name": evaluator.source_name,
                    "edge_direction": evaluator.edge_direction,
                    "evaluator_type": evaluator.evaluator_type,
                    "expression": evaluator.expression,
                }
                for evaluator in attribute.evaluators
            ],
        }
        for name, attribute in sorted(metadata.attributes.items())
    }
    payload = {
        "network_path": metadata.network_path,
        "edge_sources": source_metadata,
        "attributes": attribute_metadata,
        "travel_modes": metadata.travel_modes,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _policy_payload(settings: EligibilityConfig) -> dict[str, Any]:
    """Return deterministic policy values recorded in every cell result."""
    return {
        "h3_resolution": settings.h3_resolution,
        "travel_mode": settings.travel_mode,
        "restrictions": list(settings.restrictions),
        "intersection_policy": settings.intersection_policy,
        "representative_policy": settings.representative_policy,
        "representative_snap_tolerance_m": settings.representative_snap_tolerance_m,
        "output_crs": WGS84_CRS_NAME,
    }


def _verify_partition_parts(manifest: dict[str, Any], partition_key: str) -> None:
    """Verify all staged parts for a partition before resuming after the staged state."""
    from h3_route_data_builder.eligibility.staging import (
        StagedPart,
        read_verified_staged_part,
    )

    run_directory = Path(manifest["run_directory"])
    entries = [
        part for part in manifest["parts"] if part["partition_key"] == partition_key
    ]
    summary = manifest.get("partition_summaries", {}).get(partition_key)
    if summary is None:
        raise ValueError(f"Missing run summary for staged partition {partition_key}")
    if not entries and int(summary["cell_result_count"]) > 0:
        raise ValueError(f"No staged parts found for partition {partition_key}")
    for entry in entries:
        staged = StagedPart(
            part_key=entry["part_key"],
            path=run_directory / entry["path"],
            row_count=int(entry["row_count"]),
            checksum=entry["checksum"],
        )
        read_verified_staged_part(staged)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a deterministic JSON file via atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _build_summary(
    run_state: EligibilityRunState,
    run_directory: Path,
    manifest_path: Path,
) -> EligibilityBuildSummary:
    """Rebuild a summary for a previously completed idempotent run."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return EligibilityBuildSummary(
        run_id=run_state.run_id,
        run_directory=run_directory,
        run_status=run_state.status.value,
        expected_partition_count=len(run_state.expected_partition_keys),
        reconciled_partition_count=sum(
            status == PartitionStatus.RECONCILED
            for status in run_state.partition_status.values()
        ),
        cell_result_count=int(manifest["cell_result_count"]),
        solvable_cell_count=int(manifest["solvable_cell_count"]),
        staged_part_count=len(manifest["parts"]),
    )
