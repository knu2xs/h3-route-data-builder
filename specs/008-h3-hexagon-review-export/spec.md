# Feature Specification: H3 Hexagon Review Feature Class Export

**Feature Branch**: `008-h3-hexagon-review-export`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "Add a checkbox to the Build H3 Geometry Eligibility tool to also save
the H3 eligibility output as a feature class of hexagons, with the H3 index saved in a field and
the eligibility status retained, for interactive review. Keep H3 indices as integers and use the
BIGINT data type for storage. Add tests, update the docs and the data contract."

## Clarifications

### Session 2026-10-15

- Q: How should the H3 index be represented in the review feature class? → A: As the exact
  integer H3 index stored in a BIGINT field, for consistency with Feature 006 and the shared data
  contract. No hexadecimal representation is produced.
- Q: (Implementation finding) ArcGIS Big Integer fields reject values above 2^53 - 1 (Esri error
  161017, "Big integer values are currently limited to 53 bits"), and every valid H3 index is at
  least 2^59. How should `h3_index` be stored? → A: As a Text field (length 20) holding the exact
  decimal integer, equal to `str(h3_id)`. This supersedes the BIGINT answer above. The integer
  identity is exact; no hexadecimal representation is produced.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review Eligibility Hexagons in ArcGIS Pro (Priority: P1)

As an analyst running Build H3 Geometry Eligibility, I can check an option and name an output
feature class. The tool then also writes every evaluated H3 cell as a hexagon polygon. Each
hexagon carries its exact integer H3 index and its eligibility status, so I can add it to a map,
symbolize it by status, join it to other builder outputs, and compare it against the network
without converting the GeoParquet output myself.

**Why this priority**: This is the whole feature. Without it, analysts have to export the
GeoParquet output by hand to see which cells were classified solvable.

**Independent Test**: Run the tool on a small synthetic AOI and network with the option checked.
Confirm the feature class exists and has one hexagon per eligibility result row. Confirm each
hexagon's index and status match the matching GeoParquet row.

**Acceptance Scenarios**:

1. **Given** a valid AOI, network, and output folder, **When** the operator checks the export
   option, supplies a feature class path, and runs the tool, **Then** the GeoParquet output is
   produced exactly as before, and the feature class is also created with one polygon per
   evaluated H3 cell.
2. **Given** a completed export, **When** the operator inspects any feature, **Then** its
   `h3_index` is the exact decimal integer text of the `h3_id` integer on the matching GeoParquet row.
3. **Given** a completed export, **When** the operator inspects any feature, **Then** its
   `eligibility_status` equals the status on the matching GeoParquet row, and both solvable and
   non-solvable cells are present.
4. **Given** a completed export, **When** the operator compares a hexagon's shape with the H3
   cell boundary for its index, **Then** the vertices match, and the feature class coordinate
   system is WGS 84, the same as the GeoParquet cell geometry.

---

### User Story 2 - Default Behavior Is Unchanged (Priority: P1)

As an existing user, when I leave the new option unchecked, the tool behaves exactly as it did
before this feature.

**Why this priority**: The export is optional and must not change or put at risk the
contract-governed GeoParquet output, its fingerprint, or resume behavior.

**Independent Test**: Run the tool with the option unchecked on the same inputs as a baseline
run. Confirm no feature class is written and the GeoParquet rows, manifest, and build fingerprint
are logically identical to the baseline.

**Acceptance Scenarios**:

1. **Given** the option is unchecked, **When** the tool opens, **Then** the output feature class
   parameter is disabled and not required.
2. **Given** the option is unchecked, **When** the tool runs, **Then** no feature class is
   created, and the eligibility GeoParquet, run manifest, and build fingerprint are identical to
   a run made without this feature.
3. **Given** the option is checked, **When** the tool runs, **Then** the GeoParquet output, run
   manifest, and build fingerprint are still identical to an unchecked run on the same inputs.

---

### User Story 3 - Clear Validation and Failure Handling (Priority: P2)

As an operator, I get clear messages when the export is set up wrong or fails, and a failed
export never corrupts or hides a successful eligibility run.

**Why this priority**: The tool is used interactively in Pro, so mistakes should be caught before
a long run starts.

**Independent Test**: Use the Pro validation hooks and failure injection to confirm each message
and outcome below.

**Acceptance Scenarios**:

1. **Given** the option is checked, **When** no output feature class path is supplied, **Then**
   tool validation reports an error on that parameter and the tool cannot run.
2. **Given** the target feature class already exists and the Pro overwrite setting is off,
   **When** the tool is validated, **Then** an error tells the operator the output already
   exists.
3. **Given** the target workspace is not a geodatabase (for example, a shapefile
   folder), **When** the tool is validated, **Then** an error tells the operator to choose a
   geodatabase location.
4. **Given** the eligibility run fails or ends incomplete (for example, the hard cap is
   exceeded), **When** the tool finishes, **Then** no feature class is created or left partly
   written.
5. **Given** the eligibility run completes but the export step fails, **When** the tool
   finishes, **Then** the tool reports the export failure as an error, the completed GeoParquet
   run stays complete and reusable, and no partly written feature class is left behind.
6. **Given** a previously completed run is resumed (early return), **When** the option is
   checked, **Then** the feature class is built from that run's committed results.

---

### Edge Cases

- **Zero cells:** the AOI produces no evaluated cells. The tool creates an empty feature class
  with the defined fields and logs a warning.
- **Resumed run with leftover parts:** only parts recorded as committed in the run manifest are
  exported. Stale or superseded part files are ignored.
- **Large AOIs:** the export reads results in bounded batches, not all at once (Principle VII).
  The feature class row count must equal the manifest `cell_result_count`.
- **Index range:** valid H3 cell indices are at least 2^59 and at most 20 decimal digits, so
  every index fits the Text 20 field exactly; a numeric ArcGIS field cannot hold them (Big Integer
  is limited to 53 bits and Double rounds). An index that is not a valid H3 cell fails the export rather
  than being written.
- **Antimeridian or polar cells:** these are written exactly as stored in the GeoParquet cell
  geometry. The export does not split or repair cells.

## Requirements *(mandatory)*

### Functional Requirements

**Tool interface**

- **FR-001**: Build H3 Geometry Eligibility MUST expose an optional checkbox labeled "Also Save
  Hexagons as Feature Class". It MUST default to unchecked.
- **FR-002**: The tool MUST expose an optional output feature class parameter. It is enabled only
  when the checkbox is checked, and required when the checkbox is checked.
- **FR-003**: Both new parameters MUST come after all existing parameters. Existing parameter
  names, order, defaults, and behavior MUST NOT change.

**Feature class content**

- **FR-004**: The feature class MUST contain one polygon per evaluated H3 cell in the completed
  run, including solvable and non-solvable cells.
- **FR-005**: Each polygon MUST be that cell's canonical H3 boundary, in WGS 84, the same
  coordinate system as the GeoParquet cell geometry.
- **FR-006**: The feature class MUST have a Text field `h3_index` (length 20) holding the
  exact decimal integer H3 index, equal to `str(h3_id)` for the row. No hexadecimal
  representation MUST be produced.
- **FR-007**: The feature class MUST have a text field `eligibility_status` holding the row's
  status value unchanged.
- **FR-008**: The feature class MUST NOT have any user attribute fields other than `h3_index` and
  `eligibility_status`, apart from system-managed fields.
- **FR-009**: Features MUST be written in ascending numeric `h3_id` order, so repeated exports of
  the same run are logically identical.
- **FR-010**: Each `h3_id` MUST be validated as an H3 cell at the run's resolution before it is
  written; invalid values MUST fail the export.

**Run integration and boundaries**

- **FR-011**: The export MUST run only after the eligibility run completes and MUST read only that
  run's committed results.
- **FR-012**: The export MUST NOT change the GeoParquet output, run state, run manifest, partition
  layout, or build fingerprint.
- **FR-013**: If the export fails, the tool MUST report the failure and remove any partly written
  feature class. The completed eligibility run MUST stay complete.
- **FR-014**: The export MUST log its start, its target path, the number of features written, and
  its completion. It MUST log failures before raising them.
- **FR-015**: ArcPy-dependent export logic MUST live in the package's network/geoprocessing layer.
  The `.pyt` MUST only collect parameters and delegate.
- **FR-016**: Selecting, validating, and ordering the rows to export MUST be usable and testable
  without ArcPy.

**Tests**

- **FR-017**: Tests that need no ArcPy MUST cover committed-part selection from the manifest,
  rejection of invalid H3 IDs, and deterministic ascending ordering.
- **FR-018**: Tests that need ArcPy MUST cover the feature class schema (including the Text 20
  `h3_index` field type), row count matching the manifest, integer index and status parity with
  GeoParquet, the WGS 84 coordinate system, cleanup on failure, and an unchecked run writing no
  feature class. These tests MUST skip when ArcPy is unavailable.
- **FR-019**: Toolbox tests MUST confirm that the documented parameters in the XML sidecar match
  the tool's declared parameters, including the two new ones.

**Documentation and contract**

- **FR-020**: The tool's XML sidecar (`h3_route_data_builder.GeometryEligibilityTool.pyt.xml`)
  and its description MUST document the two new parameters, the field definitions, the
  coordinate system, the geodatabase/ArcGIS Pro version requirement, and that the feature class
  is a review aid, not a published artifact (Principle XVI).
- **FR-021**: The user documentation under `docsrc/mkdocs/` MUST describe how to enable and use
  the review export.
- **FR-022**: The shared data contract MUST gain a "Review artifacts (non-contract)" section that
  states:

    - the hexagon feature class is optional and builder-local;
    - `h3_index` is the same integer identity as contract `h3_id`, stored as exact decimal text because ArcGIS Big Integer is limited to 53 bits;
    - consumers and the solver MUST NOT treat it as contract data;
    - all contract Arrow/Parquet/JSON H3 identities remain non-null `uint64` integers.

    The contract version MUST NOT change.

### Key Entities

- **Eligibility Review Feature Class**: An optional, builder-local WGS 84 polygon dataset with one
  row per evaluated H3 cell and two attributes: `h3_index` (Text 20, exact decimal integer H3 index) and
  `eligibility_status` (text). It is derived from a completed eligibility run and is not
  versioned, fingerprinted, or published.
- **Eligibility Run (existing)**: The authoritative GeoParquet results and manifest that the
  feature class is derived from. This feature does not change it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In test runs, 100% of exported features have an index and status that match their
  GeoParquet row, and the feature count equals the run's cell result count.
- **SC-002**: With the option unchecked, eligibility output and fingerprints are identical to the
  pre-feature baseline in 100% of regression runs.
- **SC-003**: An analyst can go from tool completion to a map symbolized by eligibility status in
  under 1 minute, with no conversion steps.
- **SC-004**: When an export fails, no partly written feature class remains in 100% of cases, and
  the eligibility run status stays complete.
- **SC-005**: Data contract schema tests pass unchanged, confirming no non-integer H3 identities
  appear in contract outputs.

## Assumptions

- **Integer identity:** The review feature class uses the same integer H3 identity as Feature 006
  and the shared contract. It is stored as decimal text because ArcGIS Big Integer fields are limited to
  53 bits and every H3 index needs about 60 bits; casting `h3_index` to an integer recovers `h3_id`
  exactly.
- **Platform:** The feature runs on the project's supported ArcGIS Pro release (Python 3.11+,
  so ArcGIS Pro 3.3 or later). The review output requires a geodatabase workspace (file, mobile,
  or enterprise) for its non-nullable fields. Shapefile and other non-geodatabase
  outputs are not supported.
- **Contract coordination:** The contract change only documents a non-contract artifact. It does
  not change the solver-facing schema or version, so it needs a notice to the `h3-route-solver`
  maintainers but no coordinated adoption.
- **Cells exported:** All evaluated cells are exported, not only solvable ones, because retaining
  eligibility status is meant to support visual comparison.
- **Minimal fields:** Attributes are limited to `h3_index` and `eligibility_status`. Fields such as
  eligibility reason and edge count stay in the GeoParquet output and are out of scope.
- **Manifest and fingerprint:** The export choice and path are not recorded in the run manifest or
  fingerprint because they do not affect contract output; they are recorded in the logs.
- **Overwriting:** Overwriting an existing feature class follows the ArcGIS Pro overwrite-outputs
  environment setting.
- **Out of scope:** exporting centroid or representative points; layer files or symbology;
  exporting OD facts or published datasets; a separate standalone export tool; any change to
  eligibility logic.
- **Dependencies:** No new dependencies. The existing `h3`, `pyarrow`, and ArcPy are sufficient.
