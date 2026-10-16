---

description: "Task list for H3 Hexagon Review Feature Class Export"
---

# Tasks: H3 Hexagon Review Feature Class Export

**Input**: Design documents from `specs/008-h3-hexagon-review-export/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/review-feature-class.md](./contracts/review-feature-class.md),
[quickstart.md](./quickstart.md)

**Tests**: Required. The spec requests them explicitly (FR-017, FR-018, FR-019). Write each test
task before its implementation task and confirm it fails first.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested
independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: The user story the task belongs to (US1, US2, US3)
- Every task names the exact file path

## Ground rules for every task

- Follow `AGENTS.md` and `.specify/memory/constitution.md`: type hints on every function (no
  `from __future__ import annotations`), Google-style docstrings, `pathlib.Path`, a module-level
  `logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)`, build-message → log →
  raise for errors, and no `print()`.
- `src/h3_route_data_builder/eligibility/review.py` MUST NOT import ArcPy, directly or
  indirectly (Principle II, FR-016).
- Do not change existing public symbols, the signatures of `run_geometry_eligibility` or
  `EligibilityBuildSummary`, the existing tool parameter indices 0–8, the run manifest, or the
  build fingerprint (FR-003, FR-012).
- Do not hardcode WKIDs. Use `WGS84_CRS_NAME` from `src/h3_route_data_builder/network/geometry.py`.
- No new dependencies (R9).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the working baseline before changes.

- [X] T001 Confirm the branch is `008-h3-hexagon-review-export` and that `.specify/feature.json` points to `specs/008-h3-hexagon-review-export`. Then run `pytest testing/test_h3_route_data_builder.py testing/test_eligibility_staging.py testing/test_eligibility_output.py -q` and record the baseline pass/skip counts in the PR description notes (no file change)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: A shared synthetic completed-run fixture used by the reader and exporter tests.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Add a fixture `completed_eligibility_run(temp_dir: Path) -> Path` to `testing/conftest.py`. Without ArcPy, it builds a completed run directory in `temp_dir` and returns its path. It MUST:
    - pick a fixed `H3_TEST_RESOLUTION` and a small sorted list of valid integer H3 cells from `h3.api.basic_int`;
    - split the cells into two partitions with disjoint ascending ID ranges, and write each partition's rows in **descending** `h3_id` order to prove per-partition sorting;
    - mix `solvable` and `ineligible` `eligibility_status` values (the `EligibilityStatus` enum in `src/h3_route_data_builder/eligibility/models.py`);
    - build each table with `eligibility_results_to_table` from `src/h3_route_data_builder/eligibility/output.py`, taking geometry from an injectable `geometry_wkb_factory: Callable[[int], tuple[bytes, bytes, bytes | None]]`. The default factory returns opaque placeholder bytes `(b"cell-wkb-<id>", b"centroid-wkb-<id>", None)`, matching the existing pattern in `testing/test_eligibility_output.py`. The reader never parses geometry, and no ArcPy-free WKB encoder exists, so do not hand-encode WKB (Principle II);
    - write each part with `write_staged_part` from `src/h3_route_data_builder/eligibility/staging.py` under `run_directory / "parts" / <partition_key>`, as `run_geometry_eligibility` does;
    - write `run-manifest.json` with `run_status="complete"`, `policy.h3_resolution`, `expected_partition_keys` (`partition-000000`, `partition-000001`), `parts`, `partition_summaries`, and `cell_result_count`. Each part entry holds `partition_key`, `part_key`, a `path` relative to the run directory, `row_count`, and `checksum`. Also write a `run_directory` set to an unrelated absolute path, to prove relative resolution.

    Expose it as a factory fixture `make_completed_eligibility_run(geometry_wkb_factory=None) -> Path` plus the convenience fixture `completed_eligibility_run` that calls it with the default. Also add a fixture `manifest_rewriter` that returns a callable `(run_directory: Path, **changes: object) -> None`. The callable loads `run-manifest.json`, applies top-level key changes, and writes it back, so negative tests can change the manifest without repeating setup. Mirror the manifest key names exactly as written by `run_geometry_eligibility` in `src/h3_route_data_builder/network/workflow.py`.
- [X] T003 Add an ArcPy-gated fixture `arcpy_completed_eligibility_run(arcpy_module, make_completed_eligibility_run) -> Path` to `testing/conftest.py`. It passes a geometry factory that builds real WKB with ArcPy: `arcpy.Polygon(arcpy.Array([arcpy.Point(lon, lat) for lon, lat in ring]), spatial_reference).WKB` for the cell, and `arcpy.PointGeometry(arcpy.Point(*h3.cell_to_latlng(cell)[::-1]), spatial_reference).WKB` for the centroid. `ring` is `h3_cell_boundary(cell)` from `src/h3_route_data_builder/eligibility/cells.py`, closed by repeating the first vertex, and the spatial reference is built from `WGS84_CRS_NAME`. Letting ArcPy build the polygon gives the ring orientation ArcGIS expects. All ArcPy export tests (T005, T014, T018) use this fixture.

**Checkpoint**: `pytest testing/conftest.py --collect-only -q` succeeds, `completed_eligibility_run` builds a run directory without ArcPy, and `arcpy_completed_eligibility_run` skips cleanly without ArcPy.

---

## Phase 3: User Story 1 - Review Eligibility Hexagons in ArcGIS Pro (Priority: P1) 🎯 MVP

**Goal**: With the checkbox checked and a geodatabase path supplied, the tool also writes a
WGS 84 hexagon feature class. It has one row per evaluated cell, a Text 20 `h3_index` holding the exact decimal `h3_id`, and
`eligibility_status`.

**Independent Test**: Run `pytest testing/test_eligibility_review.py testing/test_network_review_export.py testing/test_h3_route_data_builder.py -v`.
In ArcGIS Pro, run the tool with the box checked on a small AOI. The feature class row count
equals the manifest `cell_result_count`, and each `h3_index`/`eligibility_status` matches the
GeoParquet.

### Tests for User Story 1 (write first, confirm failing) ⚠️

- [X] T004 [P] [US1] Create `testing/test_eligibility_review.py` (ArcPy-free) using `completed_eligibility_run`, with these tests:
    - `test_iter_review_cells_yields_every_manifest_row`;
    - `test_iter_review_cells_orders_h3_ids_strictly_ascending_across_partitions`;
    - `test_iter_review_cells_preserves_eligibility_status_and_geometry_wkb`, comparing against the parts read with `pyarrow.parquet`;
    - `test_iter_review_cells_ignores_unlisted_stale_part_files`, which writes an extra `.parquet` into a partition folder that the manifest does not list;
    - `test_iter_review_cells_resolves_part_paths_relative_to_run_directory`;
    - `test_expected_review_cell_count_returns_manifest_cell_result_count`;
    - `test_review_module_does_not_import_arcpy`, which asserts that `"arcpy"` is not in `sys.modules` after importing the module in a subprocess.

    Each test checks one behavior (FR-009, FR-011, FR-016, FR-017).
- [X] T005 [P] [US1] Create `testing/test_network_review_export.py`. Every test uses the `arcpy_completed_eligibility_run` fixture (T003), so it skips without ArcPy. Use `temp_gdb`, with these tests:
    - `test_export_creates_polygon_feature_class_in_wgs84`;
    - `test_export_h3_index_field_is_text_length_20`, where `arcpy.ListFields` reports type `String` and length 20 (ArcGIS Big Integer is limited to 53 bits; see research R1);
    - `test_export_eligibility_status_field_is_text_length_32`;
    - `test_export_has_no_extra_user_fields`, allowing only `h3_index`, `eligibility_status`, and system ObjectID/Shape/Shape_Length/Shape_Area fields (FR-008);
    - `test_export_row_count_equals_manifest_cell_result_count`;
    - `test_export_h3_index_and_status_match_geoparquet_in_ascending_order`, where `h3_index` values equal `str(h3_id)`;
    - `test_export_polygon_vertices_match_h3_boundary`: for each feature, the outer ring vertex set (ignoring start point and orientation) matches `h3_cell_boundary(h3_index)` within `1e-9` degrees (US1 scenario 4, FR-005);
    - `test_export_returns_written_feature_count`, which also uses `caplog` to assert INFO records for start, target path, feature count, and completion (FR-014).

    Covers FR-004–FR-008, FR-014, and FR-018.
- [X] T006 [P] [US1] Update the expected parameter list in `test_geometry_toolbox_exposes_expected_parameters` (lines 55–70) in `testing/test_h3_route_data_builder.py`. Append `"export_review_feature_class"` and `"review_feature_class"` after the existing nine names, unchanged and in order. Assert parameter 9 has datatype `GPBoolean` and default `False`. Assert parameter 10 has datatype `DEFeatureClass`, direction `Output`, and parameter type `Optional`. Keep the existing assertion that every parameter name appears in `metadata.description`, which is the XML `<idAbs>` element (FR-003, FR-019).

### Implementation for User Story 1

- [X] T007 [US1] Create `src/h3_route_data_builder/eligibility/review.py` (ArcPy-free; depends on T004) with:
    - a frozen dataclass `ReviewCell` with fields `h3_id: int`, `eligibility_status: str`, and `cell_geometry_wkb: bytes`;
    - a constant `REVIEW_MANIFEST_NAME = "run-manifest.json"`, or the existing manifest-name constant from `network/workflow.py` if it is importable without ArcPy;
    - `expected_review_cell_count(run_directory: str | os.PathLike[str]) -> int`;
    - `iter_review_cells(run_directory: str | os.PathLike[str]) -> Iterator[ReviewCell]`.

    The iterator behaves as follows:
    - Iterate `manifest["expected_partition_keys"]` in order.
    - For each partition, build `StagedPart(part_key, run_directory / entry["path"], row_count, checksum)` for every `parts` entry with that `partition_key`. Read each with `read_verified_staged_part`.
    - Concatenate the partition's tables, select only `h3_id`, `resolution`, `eligibility_status`, `cell_geometry`, and sort by `h3_id`.
    - Yield `ReviewCell` rows.
    - Never read files the manifest does not list, never write to the run directory, and hold at most one partition in memory (R3, R4).

    Log the run directory, partition count, and rows yielded at DEBUG/INFO. Add the module to the package exports only if `eligibility/__init__.py` already re-exports sibling modules' public names.
- [X] T008 [US1] Create `src/h3_route_data_builder/network/review_export.py` with `export_eligibility_review_feature_class(run_directory: str | os.PathLike[str], output_feature_class: str | os.PathLike[str]) -> int` (depends on T005, T007). It MUST:
    1. Log start and the target path.
    2. Build the WGS 84 spatial reference from `WGS84_CRS_NAME`.
    3. Call `arcpy.management.CreateFeatureclass(out_path=..., out_name=..., geometry_type="POLYGON", spatial_reference=...)`.
    4. Call `arcpy.management.AddField(in_table=..., field_name="h3_index", field_type="TEXT", field_length=20, field_is_nullable="NON_NULLABLE")`.
    5. Call `arcpy.management.AddField(in_table=..., field_name="eligibility_status", field_type="TEXT", field_length=32, field_is_nullable="NON_NULLABLE")`.
    6. Insert rows with `arcpy.da.InsertCursor(output, ["SHAPE@", "h3_index", "eligibility_status"])` inside a `with` block, using `arcpy.FromWKB(cell.cell_geometry_wkb, spatial_reference)` and `str(cell.h3_id)`, in `iter_review_cells` order.
    7. Compare the inserted count with `expected_review_cell_count`. On a mismatch, raise `ValueError`.
    8. Log the feature count and completion, and return the count.

    Split the output path into workspace and name with `pathlib.Path`. Use named parameters on every ArcPy call. Do not recompute or reproject geometry (R5).
- [X] T009 [US1] Append the two parameters to `GeometryEligibilityTool.getParameterInfo` in `arcgis/h3_route_data_builder.pyt` (depends on T006), leaving indices 0–8 untouched:
    - index 9: `arcpy.Parameter(displayName="Also Save Hexagons as Feature Class", name="export_review_feature_class", datatype="GPBoolean", parameterType="Optional", direction="Input")` with `value = False`;
    - index 10: `arcpy.Parameter(displayName="Output Hexagon Feature Class", name="review_feature_class", datatype="DEFeatureClass", parameterType="Optional", direction="Output")` with `enabled = False`.
- [X] T010 [US1] In `GeometryEligibilityTool.execute` in `arcgis/h3_route_data_builder.pyt` (depends on T008, T009), keep the existing `run_geometry_eligibility` call unchanged. After it returns, if `parameters[9].value` is true, call `export_eligibility_review_feature_class(summary.run_directory, parameters[10].valueAsText)` and log the returned feature count. Import it at the top of the `.pyt` next to the existing `from h3_route_data_builder.network.workflow import run_geometry_eligibility` (line 45), so tests can patch both names on the loaded toolbox module. The `.pyt` only delegates; add no export logic here (FR-015).
- [X] T011 [US1] In `arcgis/h3_route_data_builder.GeometryEligibilityTool.pyt.xml`:
    - add `<param>` entries for `export_review_feature_class` and `review_feature_class` after the existing nine, matching their existing structure. Include `dialogReference`/`pythonReference` text that names the fields `h3_index` (Text 20, exact decimal integer equal to `h3_id`) and `eligibility_status` (Text 32), WGS 84, and the geodatabase requirement;
    - in `<idAbs>`, extend the sentence "Parameters are aoi, …, and total_output_hard_cap." to end with "…, total_output_hard_cap, export_review_feature_class, and review_feature_class." Keep the existing phrases the test checks: "policy version 1", "inferred or set", "restore the saved values from the manifest", and "fails the run incomplete".

    The existing test reads parameter names from `metadata.description` (`<idAbs>`), so both edits are required for T006 to pass (FR-019, FR-020).

**Checkpoint**: T004–T006 pass. A Pro run with the box checked produces the review feature class. US1 is deliverable as the MVP.

---

## Phase 4: User Story 2 - Default Behavior Is Unchanged (Priority: P1)

**Goal**: With the option unchecked, the output feature class parameter is disabled and the tool
behaves exactly as before. With it checked, the GeoParquet output, manifest, and fingerprint are
still unchanged.

**Independent Test**: Run `pytest testing/test_h3_route_data_builder.py testing/test_network_review_export.py -k "unchecked or disabled or unchanged" -v`.

### Tests for User Story 2 (write first, confirm failing) ⚠️

- [X] T012 [P] [US2] Add these tests to `testing/test_h3_route_data_builder.py`:
    - `test_review_feature_class_parameter_disabled_by_default`: load the toolbox as the existing tests do; after `getParameterInfo` and `updateParameters`, parameter 10 has `enabled` False and parameter 9 value False.
    - `test_review_feature_class_parameter_enabled_when_checkbox_checked`: set parameter 9 to True, call `updateParameters`, and confirm parameter 10 is enabled.
- [X] T013 [P] [US2] Add `test_execute_unchecked_does_not_call_review_export` to `testing/test_h3_route_data_builder.py`:
    - load the toolbox module;
    - monkeypatch `run_geometry_eligibility` as the module's `execute` resolves it, returning a stub summary with `run_directory`;
    - monkeypatch `h3_route_data_builder.network.review_export.export_eligibility_review_feature_class` with a recorder;
    - run `execute` with parameter 9 False, and assert the recorder was never called.

    Also add `test_execute_checked_calls_review_export_after_run_with_summary_run_directory`, which asserts a single call with `(summary.run_directory, <parameter 10 text>)`. These tests use the `arcpy_module` fixture, because the `.pyt` imports ArcPy at module level. Monkeypatch `module.run_geometry_eligibility` and `module.export_eligibility_review_feature_class` on the toolbox module loaded with `SourceFileLoader`.
- [X] T014 [P] [US2] Add `test_export_does_not_modify_run_directory` to `testing/test_network_review_export.py` (ArcPy-gated). Snapshot each file's relative path, size, and SHA-256 under `arcpy_completed_eligibility_run` before the export, and assert they are identical after (FR-012).

### Implementation for User Story 2

- [X] T015 [US2] In `GeometryEligibilityTool.updateParameters` in `arcgis/h3_route_data_builder.pyt` (depends on T012), set `parameters[10].enabled = bool(parameters[9].value)`. Leave all existing `updateParameters` logic for indices 0–8 unchanged.
- [X] T016 [US2] Check that `src/h3_route_data_builder/network/workflow.py` is unchanged by this feature. Do not add the export choice or path to `_policy_payload`, the manifest, or the fingerprint (FR-012, spec assumptions). Then rerun `pytest testing/test_eligibility_fingerprint.py testing/test_eligibility_run_state.py -q` and confirm the results match the T001 baseline (no file change expected).

**Checkpoint**: The default tool experience and outputs are identical to the pre-feature baseline (SC-002).

---

## Phase 5: User Story 3 - Clear Validation and Failure Handling (Priority: P2)

**Goal**: Configuration mistakes are caught before running. A failed export never leaves a partial
feature class and never changes a completed run.

**Independent Test**: Run `pytest testing/test_eligibility_review.py testing/test_network_review_export.py testing/test_h3_route_data_builder.py -k "invalid or reject or cleanup or validation or incomplete or zero" -v`.

### Tests for User Story 3 (write first, confirm failing) ⚠️

- [X] T017 [P] [US3] Add these ArcPy-free tests to `testing/test_eligibility_review.py`, each asserting `ValueError`:
    - `test_iter_review_cells_rejects_incomplete_run` (`run_status="running"` via `manifest_rewriter`);
    - `test_iter_review_cells_rejects_missing_manifest`;
    - `test_iter_review_cells_rejects_part_checksum_mismatch` (corrupt one listed part's bytes);
    - `test_iter_review_cells_rejects_invalid_h3_id` (write a part containing a non-cell integer such as `0`);
    - `test_iter_review_cells_rejects_wrong_resolution` (set `policy.h3_resolution` to a different value);
    - `test_iter_review_cells_rejects_duplicate_or_descending_ids_across_partitions` (swap partition order in `expected_partition_keys`);
    - `test_iter_review_cells_rejects_empty_eligibility_status`.

    Covers FR-010 and FR-017.
- [X] T018 [P] [US3] Add these ArcPy-gated tests to `testing/test_network_review_export.py`, all using `arcpy_completed_eligibility_run`:
    - `test_export_failure_deletes_partial_feature_class`: monkeypatch `iter_review_cells` as imported by `network/review_export.py` to raise after yielding one cell; assert `ValueError` is re-raised and `arcpy.Exists(target)` is False.
    - `test_export_count_mismatch_deletes_feature_class_and_raises`: monkeypatch `expected_review_cell_count` to return count + 1.
    - `test_export_zero_cells_creates_empty_feature_class_and_warns`: build a manifest with `cell_result_count=0` and no parts, then assert the feature class exists with 0 rows and a WARNING log record via `caplog`.
    - `test_export_failure_leaves_run_status_complete`.
    - `test_export_of_resumed_completed_run_is_identical`: export the same completed run to two targets (simulating the early-return resume path, spec US3 scenario 6) and assert identical ordered `(h3_index, eligibility_status, polygon WKB)` rows.

    Covers FR-013, FR-014, and FR-018.
- [X] T019 [P] [US3] Add these ArcPy-gated toolbox validation tests to `testing/test_h3_route_data_builder.py`, using `temp_gdb` and `temp_dir`:
    - `test_validation_requires_review_feature_class_when_checked`: parameter 9 True and parameter 10 empty → parameter 10 has an error after `updateMessages`.
    - `test_validation_rejects_non_geodatabase_review_output`: parameter 10 points into a plain folder → error mentioning geodatabase.
    - `test_validation_rejects_existing_review_output_without_overwrite`: create the target first and set `arcpy.env.overwriteOutput = False` via `monkeypatch.setattr`.
    - `test_validation_ignores_empty_review_output_when_unchecked`.
- [X] T020 [P] [US3] Add `test_execute_does_not_export_when_run_raises` to `testing/test_h3_route_data_builder.py`. Monkeypatch `run_geometry_eligibility` to raise, and assert the export recorder is never called and the original exception propagates (spec US3 scenario 4).

### Implementation for User Story 3

- [X] T021 [US3] Harden `iter_review_cells` and `expected_review_cell_count` in `src/h3_route_data_builder/eligibility/review.py` (depends on T017). Raise `ValueError`, using the build-message → log → raise pattern, when:
    - the manifest is missing or is not valid JSON;
    - `run_status != "complete"`;
    - `read_verified_staged_part` fails (wrap and re-raise with the part key);
    - any `h3_id` fails `canonical_h3_ids` from `src/h3_route_data_builder/eligibility/cells.py`;
    - `h3.get_resolution(h3_id)` or the row `resolution` differs from `policy.h3_resolution`;
    - an `h3_id` is not strictly greater than the previous yielded ID;
    - `eligibility_status` or `cell_geometry` is null or empty.
- [X] T022 [US3] Wrap creation, field addition, and insertion in `export_eligibility_review_feature_class` in `src/h3_route_data_builder/network/review_export.py` with `try/except Exception` (depends on T018). On failure, it MUST:
    - log `msg` at ERROR;
    - if `arcpy.Exists(output)`, call `arcpy.management.Delete(in_data=output)` inside its own guarded block that logs, but does not mask, a delete failure;
    - re-raise the original exception.

    Log a WARNING when the written count is 0 (FR-013, FR-014; edge case "Zero cells").
- [X] T023 [US3] In `GeometryEligibilityTool.updateMessages` in `arcgis/h3_route_data_builder.pyt` (depends on T019), add these checks only when `parameters[9].value` is true. Keep existing checks for indices 0–8 unchanged.
    - If parameter 10 is empty → `parameters[10].setErrorMessage("Output Hexagon Feature Class is required when Also Save Hexagons as Feature Class is checked.")`.
    - Otherwise, if `arcpy.Describe(<parent workspace>).workspaceType` is not in `{"LocalDatabase", "RemoteDatabase"}` → `setErrorMessage("Choose a feature class in a file, mobile, or enterprise geodatabase.")` (if the parent is a feature dataset, check its geodatabase).
    - Otherwise, if `arcpy.Exists(target)` and not `arcpy.env.overwriteOutput` → `setErrorMessage("Output Hexagon Feature Class already exists; enable overwrite or choose a new name.")`.

    Guard `Describe` against a nonexistent parent and report that as the geodatabase error.
- [X] T024 [US3] Check that `GeometryEligibilityTool.execute` in `arcgis/h3_route_data_builder.pyt` calls the export only after `run_geometry_eligibility` returns, and does not catch or suppress exceptions from either call. Adjust only if T020 fails.

**Checkpoint**: All validation and failure scenarios in spec US3 pass (SC-004).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, contract, formatting, and full regression.

- [X] T025 [P] Add the "Review artifacts (non-contract)" section to `docsrc/mkdocs/design/03-data-contract.md`, using exactly the text in section 3 of `specs/008-h3-hexagon-review-export/contracts/review-feature-class.md`. Do not change any contract or schema version number (FR-022).
- [X] T026 [P] Create `docsrc/mkdocs/review-export.md`, a user guide with these sections:
    - purpose (review aid, not published);
    - how to enable it (checkbox plus output path);
    - requirements (geodatabase workspace; overwrite setting) and why `h3_index` is decimal text (ArcGIS Big Integer is limited to 53 bits);
    - a table of the fields `h3_index` and `eligibility_status`;
    - WGS 84 coordinate system;
    - joining `h3_index` to GeoParquet `h3_id`;
    - symbolizing by `eligibility_status`;
    - zero-cell and failure behavior;
    - a `!!! warning` that solver consumers must not read it as contract data.

    Follow the markdown conventions in `AGENTS.md` §3 (FR-021).
- [X] T027 Add `- Review Export: review-export.md` to the `nav` in `docsrc/mkdocs.yml`, after `- Configuration: configuration.md` (depends on T026).
- [X] T028 [P] Expand the tool-level `<summary>`/`<usage>` text in `arcgis/h3_route_data_builder.GeometryEligibilityTool.pyt.xml`. Describe the optional review export, its fields, WGS 84, the geodatabase requirement, and that it is a non-published review aid (FR-020, Principle XVI).
- [X] T029 [P] Check the docstrings in `src/h3_route_data_builder/eligibility/review.py` and `src/h3_route_data_builder/network/review_export.py`. They need `Args`/`Returns`/`Raises` sections and a fenced `python` usage example (no `Example:` header). Confirm they render in `docsrc/mkdocs/api.md` if that page auto-documents the package; add mkdocstrings entries only if the page lists modules explicitly.
- [X] T030 Run `black src testing scripts` (line length 100) and fix any style issues in the changed files.
- [X] T031 Run the full suite with `make test` (or `pytest`) in the ArcGIS Pro conda environment. Confirm that every new test passes, ArcPy-gated tests skip cleanly outside Pro, and the existing data contract schema tests pass unchanged (SC-005).
- [X] T032 Run `mkdocs build -f docsrc/mkdocs.yml --strict` and fix any broken links or nav errors from T025–T027.
- [X] T033 Do the manual ArcGIS Pro validation in `specs/008-h3-hexagon-review-export/quickstart.md`, steps 5.1–5.6. Record the results, including whether the export works in the target enterprise geodatabase if one is used, in the PR description.
- [X] T034 Draft a short notice to the `h3-route-solver` maintainers about the non-contract documentation addition (no schema or version change), and include it in the PR description.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: depends on Setup; blocks every user story (the fixture is shared).
- **US1 (Phase 3)**: depends on Foundational. This is the MVP.
- **US2 (Phase 4)**: depends on T009 (parameters exist) and T010 (execute delegates). Its tests can be written in parallel with US1 implementation.
- **US3 (Phase 5)**: depends on T007, T008, T009, and T010; it hardens those same files.
- **Polish (Phase 6)**: depends on US1–US3 being complete. T025, T026, and T028 can start once US1 is stable.

### Task-level dependencies

| Task | Depends on |
|---|---|
| T002 | T001 |
| T003 | T002 |
| T004, T005, T006 | T002, T003 |
| T007 | T004 |
| T008 | T005, T007 |
| T009 | T006 |
| T010 | T008, T009 |
| T011 | T009 |
| T012, T013, T014 | T009, T010 |
| T015 | T012 |
| T016 | T015 |
| T017 | T007 |
| T018 | T008 |
| T019, T020 | T009, T010 |
| T021 | T017 |
| T022 | T018, T021 |
| T023 | T019 |
| T024 | T020 |
| T025, T026, T028, T029 | T011 |
| T027 | T026 |
| T030 | T021–T029 |
| T031, T032 | T030 |
| T033, T034 | T031 |

### Within each user story

- Write the tests first and confirm they fail, then implement.
- Do the ArcPy-free reader (`eligibility/review.py`) before the ArcPy writer (`network/review_export.py`), then toolbox wiring (`.pyt`).
- `arcgis/h3_route_data_builder.pyt` is edited by T009, T010, T015, T023, and T024. Run these one after another, never in parallel.

## Parallel Opportunities

- **Phase 3 tests**: T004, T005, and T006 touch different files and can be written in parallel.
- **Phase 4 tests**: T012 and T013 both edit `testing/test_h3_route_data_builder.py`, so do them in order. T014 can run in parallel with them.
- **Phase 5 tests**: T017, T018, and T019/T020 are in three different files and can run in parallel. T019 and T020 share a file, so do them in order.
- **Polish**: T025, T026, T028, and T029 touch different files and can run in parallel.

### Parallel example: User Story 1

```text
Task: "T004 [US1] Create ArcPy-free reader tests in testing/test_eligibility_review.py"
Task: "T005 [US1] Create ArcPy-gated exporter tests in testing/test_network_review_export.py"
Task: "T006 [US1] Update the expected parameter list in testing/test_h3_route_data_builder.py"
```

### Parallel example: User Story 3

```text
Task: "T017 [US3] Reader rejection tests in testing/test_eligibility_review.py"
Task: "T018 [US3] Export cleanup tests in testing/test_network_review_export.py"
Task: "T019 [US3] Toolbox validation tests in testing/test_h3_route_data_builder.py"
```

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 → Phase 2 (fixture).
2. Phase 3 (T004–T011): reader, writer, parameters, delegation, and XML parameter entries.
3. **Stop and validate**: run the US1 independent test and check one run in Pro.

### Incremental delivery

1. MVP (US1): analysts can export and review hexagons.
2. US2: proves the default behavior and contract outputs are unchanged (SC-002).
3. US3: validation messages and failure cleanup (SC-004).
4. Polish: data contract section, user guide, sidecar summary, formatting, full regression, and the solver notice.

### Suggested commits (Conventional Commits)

- `test(eligibility): add completed-run fixture for review export` (Phase 2)
- `feat(eligibility): add ArcPy-free review cell reader` (T004, T007, T017, T021)
- `feat(network): export eligibility review hexagon feature class` (T005, T008, T014, T018, T022)
- `feat(toolbox): add optional hexagon review export parameters` (T006, T009–T013, T015, T019, T020, T023, T024)
- `docs: document hexagon review export and non-contract artifact` (T025–T029)
