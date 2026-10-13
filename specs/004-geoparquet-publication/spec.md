# Feature Specification: GeoParquet Publication

**Feature Branch**: `[004-geoparquet-publication]`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "Create Builder Feature 004: GeoParquet Publication. Read the shared
constitution and builder Features 001, 002, 003, and 005 before drafting. Specify how validated OD
results and the solvable-cell dimension are published as a versioned, interoperable dataset.
Define the logical division, canonical schemas, identifiers, units, nullability, schema versioning,
origin partitioning and pruning, GeoParquet metadata, manifests, atomic publication, compaction,
and detection/reporting of incomplete or corrupt output. Keep library, file-layout, and deployment
choices open unless needed to make contracts testable. Do not redefine candidate generation,
solve lifecycle, or parallel-worker policy."

## Clarifications

### Session 2026-10-13

- Q: In proximal mode, should the cutoff-bounded destination area be built around every in-AOI
  origin, or only around origin cells the operator selects? → A: Generate proximal destinations
  separately for every solvable origin inside the AOI.
- Q: In AOI-wide mode, should every in-AOI candidate pair be solved even when the actual route
  exceeds the configured cutoff, or should over-cutoff routes be excluded after solving? → A: AOI-wide
  mode considers all in-AOI candidate pairs retained by Feature 002's conservative prefilter for
  solving, but the configured actual-cost cutoff still determines which solved routes qualify for
  publication.
- Q: Should the published cell dimension include every solvable origin and destination in the
  selected Feature 002 scope, even when prefiltering removes all pairs involving a cell, or only
  cells referenced by retained pairs? → A: Include every solvable cell in the selected origin and
  destination scope, regardless of whether its candidate pairs survive the prefilter.
- Q: Should pairs removed by Feature 002’s conservative prefilter be included in Feature 004’s
  expected-key reconciliation, or excluded from publication completeness? → A: Exclude prefilter-pruned
  pairs from publication’s expected-key set; preserve their counts and provenance only.
- Q: Should Feature 004 prohibit GeoPandas in all production and validation code? → A: Do not use
  GeoPandas anywhere in this project; use ArcGIS GeoAccessor for spatial Pandas operations and
  DuckDB with its spatial extension for large spatial processing.
- Q: In AOI-wide mode, should the planner bypass the cutoff-based prefilter and schedule every
  directed in-AOI pair? → A: No; retain Feature 002's prefilter, with AOI-wide covering every
  in-AOI pair retained by that planner.
- Q: Does requiring the ArcGIS GeoAccessor for spatial Pandas operations prevent using Arrow/PyArrow
  for publication schemas, columnar interchange, and Parquet/GeoParquet I/O? → A: No; Arrow/PyArrow
  is an approved and preferred fit for columnar schemas, interchange, Parquet/GeoParquet
  serialization, and metadata validation. The GeoAccessor requirement applies to spatial operations
  performed through Pandas, while large spatial processing uses DuckDB Spatial.
- Q: Must User Story 1 produce and validate GeoParquet outputs, or only define canonical tables?
  → A: User Story 1 must write the solvable-cell dimension and OD facts as GeoParquet and validate
  their schema, GeoParquet metadata, and readable logical rows with PyArrow and DuckDB. It does not
  expose a complete atomic dataset version or `_SUCCESS`; that publication lifecycle belongs to
  User Story 2.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce and Read GeoParquet Tables (Priority: P1)

As a route-data consumer, I need validated GeoParquet cell and OD tables with stable identifiers,
documented costs, and interoperable geometry metadata so that I can read and join routes to
eligible cells without depending on ArcGIS.

**Why this priority**: Interoperable, correctly described facts and spatial dimensions are the
primary value delivered by publication.

**Independent Test**: Write the solvable-cell dimension and OD facts from a small Feature 001/002/003
fixture as GeoParquet files. Validate their schemas and GeoParquet metadata with PyArrow, read the
files with PyArrow and DuckDB Spatial, and compare identifiers, units, geometries, and logical rows
with independent expected values. This test does not require atomic publication or a completion
marker; those are validated by User Story 2.

**Acceptance Scenarios**:

1. **Given** a Feature 001 eligibility result and Feature 003's reconciled solve outcomes, **When**
   User Story 1 writes the fixture outputs, **Then** it produces GeoParquet files for the cell
   dimension and OD facts containing exactly the distinct in-scope solvable cells and qualifying
   route outcomes plus Feature 002 self-pairs.
2. **Given** an OD fact with origin `A` and destination `B`, **When** a fact with reversed
   endpoints exists, **Then** the two facts have distinct directed keys and can be joined
   independently to the corresponding solvable cells.
3. **Given** any published geometry column, **When** an ArcPy-free consumer reads it, **Then** it
   receives the declared geometry type and complete WGS 84 / EPSG:4326 CRS metadata.
4. **Given** a cell dimension row, **When** its source eligibility evidence is checked, **Then**
   its H3 identifier, eligibility status, deterministic representative, and eligibility fingerprint
   satisfy Feature 001's solvable-cell contract.
5. **Given** a solvable cell in the selected Feature 002 origin/destination scope, **When** every
   candidate pair involving it is removed by the conservative prefilter, **Then** the cell remains
   in the published dimension even though those pruned keys do not enter publication key
   reconciliation.
6. **Given** the GeoParquet files written by User Story 1, **When** they are validated, **Then**
   PyArrow confirms the canonical schemas and required GeoParquet geometry metadata, and PyArrow
   and DuckDB Spatial can read the expected logical rows without ArcPy. These files are not
   exposed as a complete dataset version and have no valid completion marker until User Story 2
   completes atomic publication.

### User Story 2 - Publish Only a Complete Valid Snapshot (Priority: P1)

As a builder operator, I need publication to remain unavailable until every expected result and
metadata check passes so that a partial, corrupt, or inconsistent build cannot be mistaken for a
usable dataset.

**Why this priority**: Consumers must be able to distinguish an authoritative dataset from staged
or incomplete work.

**Independent Test**: Interrupt publication at each staging and exposure boundary, corrupt or omit
individual files and manifest records, and verify readers see either the previous complete version
or the new validated version, never a partial success.

**Acceptance Scenarios**:

1. **Given** expected logical OD keys with unresolved work, **When** publication is attempted,
   **Then** it remains incomplete, exposes no success marker, and reports the unresolved keys or
   their durable counts.
2. **Given** staged outputs whose schemas, checksums, row counts, geometries, or logical keys do
   not validate, **When** publication validation runs, **Then** the version is rejected and no
   success marker is exposed.
3. **Given** all required validations pass, **When** the new version is exposed, **Then** readers
   observe its manifests, all referenced immutable data parts, and completion marker as one
   complete snapshot.
4. **Given** an already published version, **When** a later build publishes or compacts data,
   **Then** it does not modify the existing version's data parts or manifests in place.

### User Story 3 - Prune and Compact Published Data (Priority: P2)

As a data analyst or maintainer, I need origin-based reads to skip unrelated OD data and compaction
to reduce inefficient physical layout without changing route meaning, so that common origin
queries remain efficient and maintenance is safe.

**Why this priority**: Large sparse OD datasets are primarily queried by origin, and repeated
publication can fragment physical layout.

**Independent Test**: Query a multi-origin fixture for a subset of origins and measure that
unrequested origin partitions are skipped; compact the fixture and compare all logical records and
identifiers before and after.

**Acceptance Scenarios**:

1. **Given** OD facts spanning multiple canonical solvable origins, **When** a consumer filters by
   one origin, **Then** partition metadata and row-group statistics allow unrelated origin data to
   be pruned without scanning it.
2. **Given** a valid published version, **When** it is compacted, **Then** fact and dimension
   logical rows, directed keys, values, and identifiers remain equivalent while new physical
   manifests describe the compacted layout.
3. **Given** a file or partition with a checksum or row-count mismatch, **When** a consumer or
   validation tool inspects the version, **Then** the version is reported as corrupt or incomplete
   and is not reported as successfully published.

### Edge Cases

- A valid build has no qualifying non-self routes, but does have self-pairs and/or resolved
  non-route outcomes.
- A zero-cell, zero-candidate build produces valid empty outputs with explicit zero counts and a
  valid completion manifest, provided every expected input and solve disposition reconciles.
- Unlocated, unreachable, and cutoff-excluded outcomes are recorded as reconciled non-route
  dispositions but MUST NOT appear as OD facts; Feature 003 treats unlocated and unreachable as
  equivalent unroutable outcomes for downstream analysis.
- A terminal system failure or unresolved/retryable key prevents successful final publication;
  a diagnostic incomplete staging result may be retained without a completion marker.
- Two origins share a physical file or row group; its manifest and origin metadata still permit
  filtering without confusing file identity with a logical OD key.
- A compacted part spans multiple origins or has a different row order; logical origin partition
  keys and pruning statistics remain correct.
- A cell geometry crosses a partition or file extent boundary; its recorded extent and covering
  metadata enclose the complete geometry.
- A checksum, row count, extent, schema version, CRS declaration, expected key set, or manifest
  reference is missing or inconsistent.
- An unsupported or newer schema or GeoParquet specification is encountered; readers reject or
  clearly report incompatibility rather than silently interpreting it as the current contract.
- Re-publication attempts to expose a version ID that already identifies different logical data;
  the existing immutable version is not overwritten.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The published dataset MUST consist of two logical tables: a solvable-cell dimension
  and directed OD facts. Cell polygon, centroid, and network representative geometry MUST be stored
  in the solvable-cell dimension, not repeated in OD facts. OD facts MUST identify both endpoints
  and MUST NOT carry endpoint geometry.
- **FR-002**: The solvable-cell dimension MUST contain exactly one row per distinct canonical
  solvable H3 cell in Feature 002's resolved origin and destination cell scopes for the published
  build, including cells whose candidate pairs are all removed by the conservative prefilter.
  Membership MUST NOT depend only on whether a retained logical key references the cell. Each row
  MUST have `eligibility_status=solvable`; ineligible, missing, or representative-invalid cells
  MUST NOT be published in this dimension.
- **FR-003**: The solvable-cell schema MUST include the following fields, with the stated
  canonical meaning and nullability:

  | Field | Canonical type | Nullability and meaning |
  |---|---|---|
  | `h3_id_hex` | string | Required; canonical H3 hexadecimal identifier, lowercase and normalized |
  | `h3_id_uint64` | unsigned 64-bit integer | Nullable alternate representation when safely representable by consumers |
  | `resolution` | unsigned 8-bit integer | Required; H3 resolution matching `h3_id_hex` |
  | `cell_geometry` | Polygon geometry | Required; canonical H3 cell polygon |
  | `centroid_geometry` | Point geometry | Required; canonical H3 cell centroid |
  | `representative_geometry` | Point geometry | Required; Feature 001 deterministic network representative |
  | `intersecting_edge_count` | unsigned 32-bit integer | Required; nonnegative count of distinct eligible intersecting edges |
  | `network_source_id` | signed 32-bit integer | Required; representative's Network Analyst source identifier |
  | `network_source_oid` | signed 64-bit integer | Required; representative's source object identifier |
  | `network_pos_along` | 64-bit float | Required; finite normalized position along the network source |
  | `network_side_of_edge` | signed 8-bit integer | Required; validated Network Analyst side-of-edge value |
  | `representative_snap_distance_m` | 64-bit float | Required; finite, nonnegative representative snap distance in meters |
  | `eligibility_status` | string | Required; exactly `solvable` for every published row |
  | `eligibility_reason` | string | Required; Feature 001 reason code or description supporting the status |
  | `eligibility_fingerprint` | string | Required; identifies the Feature 001 eligibility evidence and policy |

- **FR-004**: Every persisted geometry MUST be WGS 84 / EPSG:4326, with valid GeoParquet
  metadata containing complete CRS PROJJSON. Geometry metadata MUST declare the actual geometry
  type and encoding. Each geometry MUST have usable bounding-box or covering metadata, and
  spatial ordering MUST be deterministic and recorded in the dataset manifest. The selected
  publication contract MUST conform to GeoParquet 1.1.0.
- **FR-005**: OD facts MUST use the ordered endpoint tuple
  `(origin_h3_id_hex, destination_h3_id_hex)` as their logical key. The key MUST be unique within
  the active dataset, direction-sensitive, canonical, and independent of work-item ID, dataset
  version, partition, or file name. A surrogate key MAY be added but MUST NOT replace or redefine
  this logical key.
- **FR-006**: The OD-fact schema MUST include the following fields, with the stated canonical
  meaning and nullability:

  | Field | Canonical type | Nullability and meaning |
  |---|---|---|
  | `origin_h3_id_hex` | string | Required; canonical solvable origin H3 identifier |
  | `destination_h3_id_hex` | string | Required; canonical solvable destination H3 identifier |
  | `travel_mode` | string | Required; configured travel mode used for the compatible solve |
  | `network_distance_m` | 64-bit float | Nullable only when no actual distance measure is available; otherwise finite, nonnegative meters |
  | `network_time_s` | 64-bit float | Nullable only when no actual time measure is available; otherwise finite, nonnegative seconds |
  | `origin_representative_snap_distance_m` | 64-bit float | Required; finite, nonnegative value copied from the origin dimension |
  | `destination_representative_snap_distance_m` | 64-bit float | Required; finite, nonnegative value copied from the destination dimension |
  | `solve_status` | string | Required; exactly `solved` or `self_pair` for published facts |
  | `work_item_id` | string | Nullable only for self-pairs, which are resolved without Feature 003 network work |
  | `build_fingerprint` | string | Required; compatible result fingerprint defined by Feature 003 |

  At least one of `network_distance_m` or `network_time_s` MUST be present for every fact, and
  the field corresponding to the configured actual network impedance MUST be present for solved
  routes. Values MUST represent actual network solve results and MUST use the stated units; the
  publisher MUST NOT convert estimates or stretch values into network costs. Both cost fields
  MUST be zero for Feature 002 self-pairs.
- **FR-007**: Each non-self OD fact MUST have two endpoints in the published solvable-cell
  dimension, a compatible Feature 003 committed qualifying outcome, and exactly one authoritative
  fact for its logical key. Each Feature 002 self-pair MUST have a single `self_pair` fact with
  zero network cost and MUST NOT require a network work item. Reverse-direction facts MUST remain
  separate.
- **FR-008**: Unlocated, unreachable, cutoff-excluded, retryable, and terminal-failure outcomes
  MUST NOT be serialized as qualifying OD facts or assigned success-shaped network costs.
  Unlocated, unreachable, and cutoff-excluded outcomes MUST be represented in publication
  reconciliation counts and provenance, not as route facts. Any unresolved, retryable, or
  terminal system-failure key MUST prevent successful final publication. AOI-wide candidate scope
  MUST NOT disable or bypass Feature 002/003's configured actual-network-cost cutoff.
- **FR-009**: Fact data MUST be partitioned by canonical solvable-origin H3 identifier. The origin
  identifier MUST remain available as a typed row field and in partition metadata. Dataset and
  partition metadata MUST support origin-based pruning, including when physical parts contain
  more than one origin. The cell dimension MUST use a deterministic spatially locality-preserving
  order; its ordering policy and any row-group spatial statistics MUST be recorded.
- **FR-010**: Every dataset publication MUST have a manifest identifying its immutable dataset
  version and containing, at minimum: publication state, creation time, logical dataset and
  compatibility fingerprints, Feature 001 eligibility fingerprint, Feature 002 candidate/run
  provenance including the selected candidate scope mode (`proximal` or `AOI-wide`), Feature 003
  solve reconciliation state, expected and published logical-key counts, solvable-cell dimension
  row count, classified excluded-outcome counts, prefilter-pruned pair count, cell and fact schemas
  and versions, GeoParquet version, geometry CRS and covering conventions, partition scheme,
  spatial-ordering policy, and references to every required dimension and fact partition manifest.
- **FR-011**: Each partition manifest MUST identify its logical table and partition keys and list
  each immutable data part with its relative location, checksum and named checksum algorithm, row
  count, schema version, and applicable geometry extent/CRS. Manifests MUST include partition
  totals that reconcile exactly to the rows and files they reference. Dataset and partition
  manifests MUST contain enough information to validate cross-table endpoint membership and
  logical-key uniqueness.
- **FR-012**: Publication MUST be staged and remain undiscoverable as a successful dataset until
  schema, GeoParquet metadata, CRS, geometry extents, checksums, row counts, partition references,
  endpoint membership, expected-key coverage, and uniqueness validations all pass. The immutable
  parts and authoritative dataset manifest MUST be exposed as one complete version. On stores
  without atomic directory replacement, an equivalent single atomic publication-reference update
  MUST provide this visibility guarantee.
- **FR-013**: `_SUCCESS` or an equivalent completion marker MUST be absent from incomplete,
  rejected, or merely staged output. It MUST be written or exposed only after all required data and
  manifest validations pass and the publication reference identifies the complete version.
  Consumers MUST treat output without a valid completion marker and matching complete manifest as
  incomplete, regardless of filenames, process status, or presence of individual data parts.
- **FR-014**: The solvable-cell dimension MUST cover all distinct solvable cells in Feature 002's
  selected origin/destination cell scopes, irrespective of whether all pairs involving a cell are
  later pruned. A successful publication MUST reconcile Feature 002's retained non-self candidates
  and self-pairs with Feature 003's authoritative per-key outcomes. Pairs removed by Feature 002's
  conservative prefilter MUST be excluded from the publication expected-key set and fact-key
  reconciliation; their counts and candidate-policy provenance MUST remain in the dataset
  manifest. Every retained non-self key MUST have exactly one compatible qualifying route or a
  durable resolved non-route classification (`unlocated`, `unreachable`, or `cutoff-excluded`).
  This applies to both proximal and AOI-wide candidate scopes: AOI-wide scope considers every
  in-AOI candidate pair retained by Feature 002's conservative prefilter and does not waive the
  configured actual-cost cutoff. Facts MUST equal the qualifying-route keys plus the Feature 002
  self-pair keys exactly. Any missing, duplicate,
  unexpected, conflicting, or unresolved retained key MUST prevent success and MUST be reported
  distinctly from a valid empty result.
- **FR-015**: Validation MUST detect and report incomplete manifests or files, checksum mismatch,
  row-count mismatch, corrupt or unreadable parts, schema/spec incompatibility, invalid geometry
  metadata, CRS inconsistency, duplicate logical OD keys, endpoint references absent from the
  solvable-cell dimension, incompatible fingerprints, unaccounted expected keys, and contradictory
  partition metadata. Detection MUST NOT silently repair or present invalid data as successfully
  published.
- **FR-016**: Compaction MAY combine, split, reorder, or rewrite physical parts, but MUST publish a
  new immutable physical version with updated manifests, checksums, extents, and row counts. It
  MUST preserve all logical cell rows and OD facts, logical identifiers, typed values, units,
  nullability, eligibility evidence, CRS, and publication semantics exactly. No prior published
  part may be changed in place.
- **FR-017**: Dataset and schema contracts MUST be explicitly versioned. Any incompatible field,
  identifier, geometry, unit, nullability, or semantic change MUST receive a new schema version
  and MUST NOT be misrepresented as backward-compatible. Readers MUST be able to identify an
  unsupported schema or GeoParquet version before treating the dataset as valid.
- **FR-018**: This feature MUST own final schemas, physical dataset publication, publication
  manifests, validation, completion visibility, and compaction. Feature 001 continues to own cell
  eligibility and deterministic representatives; Feature 002 continues to own candidate universe,
  directed keys, self-pairs, per-origin destination scope, and origin batching; when Feature 002
  supplies proximal-mode candidates, it MUST define that scope separately for each solvable
  in-AOI origin. Feature 003 continues to own solve outcomes and ledger reconciliation; Feature
  005 continues to own worker concurrency, isolated scratch, and serial fallback. Publication MUST
  preserve the selected candidate scope as provenance and consume these contracts without
  redefining their generation or solve semantics.
- **FR-019**: Feature 004 MUST NOT install, import, or use GeoPandas in publication code, tests, or
  tooling. ArcPy-free consumer compatibility MUST be validated with PyArrow and DuckDB. When
  columnar schemas, interchange, Parquet/GeoParquet serialization, or metadata validation are
  required, Arrow/PyArrow SHOULD be used where appropriate. The ArcGIS GeoAccessor requirement
  applies to spatial operations performed through Pandas; large spatial processing MUST use DuckDB
  with its spatial extension.

### Key Entities *(include if feature involves data)*

- **Solvable-cell dimension**: One row for each distinct eligible H3 endpoint cell, holding its
  canonical identifier, eligibility evidence, and cell, centroid, and network-representative
  geometry.
- **OD fact**: A qualifying directed route result or a Feature 002 self-pair, keyed by its ordered
  origin and destination identifiers and linked to two dimension rows.
- **Logical OD key**: The direction-sensitive ordered origin/destination H3 identifier pair,
  independent of physical storage, work item, or publication version.
- **Dataset manifest**: Versioned declaration of schemas, fingerprints, completeness, solve
  reconciliation, partition layout, GeoParquet conventions, and referenced partition manifests.
- **Partition manifest**: Integrity and statistics record for a logical table partition and its
  immutable physical parts.
- **Completion marker**: Evidence that one manifest-identified version passed all required
  validation and was atomically exposed for consumption.
- **Compacted version**: A new physical organization of an existing logical dataset whose logical
  rows, identifiers, and meaning remain unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of published geometry columns validate against GeoParquet 1.1.0, report the
  declared geometry type and complete WGS 84 / EPSG:4326 CRS PROJJSON, and expose usable covering
  or bounding-box metadata.
- **SC-002**: PyArrow and DuckDB read the published cell dimension and OD facts without ArcPy;
  independently computed schemas, canonical keys, units, and logical row values match 100% of
  fixture records.
- **SC-003**: On a multi-origin fixture, filtering to one origin reads zero unrelated origin
  partitions and demonstrably skips their files or row groups using published pruning metadata.
- **SC-004**: 100% of manifest-listed checksums, file row counts, partition totals, geometry
  extents, schema versions, and expected fact counts reconcile with the independently inspected
  output.
- **SC-005**: Fault-injection tests at staging, validation, manifest creation, and publication
  exposure observe either the previous complete version or the new complete version; no
  incomplete version has a valid completion marker or is presented as published.
- **SC-006**: Compaction produces 100% logical equivalence for dimension and fact rows, keys,
  values, units, eligibility evidence, and semantics, with zero duplicate logical OD keys and no
  mutation of the prior version.
- **SC-007**: 100% of published solvable-cell rows satisfy Feature 001's solvable eligibility and
  representative contract, and 100% of fact endpoints resolve to exactly one such dimension row.
- **SC-008**: Injected missing, duplicate, unexpected, corrupt, incompatible, or inconsistent
  output is detected and reported in every corresponding validation case, and none is marked
  successfully published.
- **SC-009**: For every successful publication, each expected logical key is accounted for exactly
  once as a qualifying fact or resolved non-route classification; unresolved, retryable, and
  terminal system-failure work produces an incomplete publication state.
- **SC-010**: Dependency, import, and test checks find zero GeoPandas dependencies, imports, or
  uses in Feature 004; the required ArcPy-free reader checks pass with PyArrow and DuckDB.

## Assumptions

- The GeoParquet contract is fixed to version 1.1.0 for this feature; ArcPy-free consumer
  compatibility is verified against PyArrow and DuckDB. GeoPandas is not used in this project.
- Arrow/PyArrow is appropriate for columnar schemas, interchange, Parquet/GeoParquet I/O, and
  metadata validation; it does not replace the required spatial-operation tools.
- When spatial operations use Pandas, they use the ArcGIS GeoAccessor; large spatial processing
  uses DuckDB with the spatial extension.
- Feature 001 supplies canonical solvable-cell records, deterministic representatives, eligibility
  evidence, and WGS 84 / EPSG:4326 geometries with CRS metadata.
- Feature 002 supplies the expected directed logical OD keys, self-pairs, canonical solvable
  origin identifiers, selected candidate scope mode and candidate provenance. In proximal mode,
  candidate destination scope is determined separately for every solvable in-AOI origin. In
  AOI-wide mode, candidate pairs cover every in-AOI pair retained by Feature 002's conservative
  prefilter; the configured actual-cost cutoff still determines which solved routes qualify for
  facts.
- Feature 003 supplies compatible committed qualifying outcomes and per-key reconciled
  classifications. Publication does not infer success from work-item status or staged file
  presence.
- A final successful publication requires every expected key to have a qualifying route or a
  resolved non-route classification. System failures that remain unresolved prevent a successful
  final publication.
- Unlocated, unreachable, and cutoff-excluded dispositions are useful for reconciliation and
  diagnostics but are not route facts in the consumer dataset.
- The dataset is immutable by version. A later build or compaction creates a new version; atomic
  rename, catalog update, or another equivalent visibility mechanism is an implementation choice.
- Hash algorithm, directory and file names, partition encoding, compression, compaction trigger,
  geometry encoding, and exact spatial ordering algorithm are implementation choices provided
  their resulting contract and provenance are testable.

## Scope Boundaries

- Candidate selection, cutoff reach, logical-key creation policy, self-pair planning, and
  destination batching remain owned by Feature 002.
- Durable solve states, leases, retry and invalidation behavior, outcome classification, and
  authoritative result reconciliation remain owned by Feature 003.
- Concurrent ArcPy capability probing, worker scheduling, per-worker scratch, and serial fallback
  remain owned by Feature 005.
- Geometry eligibility, representative creation, CRS processing, and solvable status remain owned
  by Feature 001.
