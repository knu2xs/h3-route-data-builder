# Feature Specification: Spatial Data Engine Standardization

**Feature Branch**: No branch created; active branch remains `main`.

**Feature Directory**: `specs/007-spatial-data-engines`

**Created**: 2026-10-15

**Status**: Draft

**Input**: Standardize small, memory-resident spatial data processing on Pandas with the ArcGIS
GeoAccessor; use DuckDB, with its spatial extension when needed, as data scales. Use on-disk
DuckDB instead of SQLite for persistent databases. Amend the constitution and align builder code.

## Clarifications

### Session 2026-10-15

- Q: If DuckDB Spatial cannot reproduce a required geometry operation exactly, should the large-data
  path delegate that operation to bounded ArcGIS batches or stop the build? A: Delegate only
  unsupported or non-equivalent operations to explicitly recorded, bounded GeoAccessor/ArcPy
  batches, preserving the memory budget and existing geometry semantics.
- Q: Should a build automatically download a missing DuckDB Spatial extension, or require it to
  be installed before the build starts? A: Provision it during environment setup; builds only
  load it and fail with setup guidance if it is missing. No runtime downloads are permitted.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Process Small Spatial Inputs Consistently (Priority: P1)

As a builder operator, I want small spatial workloads to use the approved in-memory path without
changing eligible cells, representatives, directed candidate pairs, or solved costs.

**Why this priority**: A consistent small-data path makes behavior predictable and provides the
reference against which the scale-out path can be checked.

**Independent Test**: Run synthetic AOI, edge, and cell fixtures through the small-data path and
compare their logical results with fixed pre-change expectations, including exact H3 identities.

**Acceptance Scenarios**:

1. **Given** valid spatial inputs whose estimated working set fits the resolved memory budget,
   **When** eligibility and candidate geometry are evaluated, **Then** the in-memory path is used
   and the engine decision, resource policy, CRS, and relevant versions are recorded.
2. **Given** crossing, touching, nearby-but-not-intersecting, restricted, one-way, disconnected,
   and representative tie fixtures, **When** processing completes, **Then** membership,
   classifications, and deterministic representative choices match the reference expectations.
3. **Given** valid H3 cells across resolutions 0-15, including values above `2^53`, **When** data
   crosses spatial tables, representative transport, solve results, and publication boundaries,
   **Then** every identity remains an exact integer without float or text coercion.
4. **Given** the in-memory spatial dependency or required ArcGIS geometry capability is unavailable,
   **When** the path is requested, **Then** the build fails with actionable prerequisite guidance
   rather than silently choosing an unapproved geometry engine or reporting successful empty output.

---

### User Story 2 - Process Large Data Without Full Materialization (Priority: P1)

As a builder operator, I want workloads that exceed the small-data budget to use bounded,
disk-capable processing while producing the same logical dataset.

**Why this priority**: Standardization must work at production scale, not merely replace one
in-memory representation with another that exhausts memory.

**Independent Test**: Run the same conformance fixture on both paths using controlled resource
budgets, then run an input larger than the permitted in-memory working set and inspect resource
instrumentation and reconciled output.

**Acceptance Scenarios**:

1. **Given** a working-set estimate above the memory budget, or an unknown estimate that cannot
   safely establish an in-memory fit, **When** processing begins, **Then** the large-data path is
   selected before loading the complete input into an in-memory spatial table.
2. **Given** the same inputs, policies, and declared numerical tolerances, **When** each path runs,
   **Then** eligible cells, directed keys, outcome classes, and deterministic representatives agree,
   and geometry-derived quantities agree within those tolerances.
3. **Given** a large non-spatial aggregation or ledger operation, **When** it runs, **Then** no
   spatial extension or ArcGIS spatial import is required solely because the engine is DuckDB.
4. **Given** an operation requiring the spatial extension and that extension is unavailable,
   **When** the operation is attempted, **Then** it fails explicitly without authoritative partial
   output or a runtime download attempt, and the operator receives installation/loading guidance.
5. **Given** insufficient temporary disk space, an exceeded memory limit, or a failed spatial
   operation, **When** execution stops, **Then** durable completed work remains recoverable and
   the incomplete run is not published as successful.
6. **Given** a required geometry operation is unsupported or non-equivalent in DuckDB Spatial,
   **When** the large-data path evaluates it, **Then** it delegates only that operation to bounded
   GeoAccessor/ArcPy batches, records the delegation, and preserves the resolved memory budget
   and reference semantics without materializing the complete dataset.

---

### User Story 3 - Resume Work from a Durable Database (Priority: P1)

As a builder operator, I want the durable ledger stored in an on-disk DuckDB database so the
approved database engine also supports safe restart and bounded parallel solving.

**Why this priority**: Replacing persistence must retain the existing no-loss, no-duplicate
guarantees; engine uniformity alone is not sufficient.

**Independent Test**: Interrupt and reopen a bounded solve at every durable lifecycle boundary,
then reconcile expected directed keys and verify immutable committed parts.

**Acceptance Scenarios**:

1. **Given** a fresh ledger, **When** the coordinator records work, closes the database, and a new
   process reopens it, **Then** exact work identities, expected keys, attempts, leases, fencing,
   failures, and committed-part references are restored.
2. **Given** interruption after planning, leasing, solving, staging, validation, or result commit,
   **When** recovery runs, **Then** no committed logical result is lost or duplicated, and an
   uncommitted part cannot masquerade as completed work.
3. **Given** an expired lease and a replacement assignment, **When** an old worker returns,
   **Then** its stale result is rejected and only the current fenced assignment may be accepted.
4. **Given** concurrent solve workers, **When** their results arrive, **Then** only the coordinator
   accesses the authoritative read-write database; worker payloads contain no live database handle
   and workers never open that database directly.
5. **Given** an active coordinator, **When** a second process requests read-write ownership of the
   same ledger, **Then** it is refused clearly without mutating work or bypassing fencing.
6. **Given** invalid staged output, a transaction failure, a crash around part visibility, or a
   terminal solve failure, **When** reconciliation runs, **Then** the existing lifecycle and
   failure-classification rules determine completion, not filenames or process exit status.

---

### User Story 4 - Adopt the Policy Without Rewriting History (Priority: P2)

As a maintainer, I want governance, code, and operator guidance to describe one coherent engine
policy, with an explicit pre-alpha cutover from existing SQLite working databases.

**Why this priority**: Operators must know which state can resume and which requires a fresh build;
maintainers must not be left with conflicting geometry mandates.

**Independent Test**: Review amended governance against all engine entry points, and attempt the
cutover using a legacy SQLite ledger plus historical publication fixtures.

**Acceptance Scenarios**:

1. **Given** the present ArcPy-only eligibility geometry rule, **When** the amendment is adopted,
   **Then** governance permits GeoAccessor for small spatial workloads and DuckDB Spatial for
   larger ones, while retaining ArcPy for Network Analyst and necessary geoprocessing boundaries.
2. **Given** an existing SQLite ledger, including journal/WAL sidecars, **When** an operator selects
   it for the new build, **Then** it is rejected with separate-fresh-ledger guidance and every
   original file remains byte-for-byte unchanged. Renaming it does not make it compatible.
3. **Given** a fresh DuckDB ledger and the same source inputs, **When** work is scheduled, **Then**
   it starts without claiming reuse from the legacy database; subsequent compatible restarts and
   AOI expansions reuse new-format completed work according to existing candidate/lifecycle rules.
4. **Given** historical publications, **When** new working storage is adopted, **Then** old
   publications remain immutable and new publications retain the current external schema.

### Edge Cases

- Empty inputs and zero planned work must reconcile without starting unnecessary spatial work.
- The estimated working set equals the budget, exceeds it by one unit, or cannot be estimated.
- A resource snapshot changes between runs or during a restart.
- Valid empty datasets reconcile as zero work. Empty/invalid individual geometry and missing CRS
  fail validation unless an existing explicit rule defines otherwise; they are not empty datasets.
- Valid antimeridian-crossing geometry preserves reference semantics through conservative filtering
  and bounded exact checks. Unsupported operations delegate under FR-008 or fail explicitly.
- A geometric predicate near a boundary could change eligibility or a representative tie.
- Nullable non-identity integer attributes must not trigger float conversion of required H3 columns.
- A requested spatial operation is unsupported by the selected engine.
- Extension loading is unavailable in an offline ArcGIS Pro environment.
- A database is corrupt, incompatible, locked by another coordinator, or has recoverable
  transaction-log state after interruption.
- Temporary storage fills during spilling, staging, or commit.
- A worker is terminated or delivers a duplicate, delayed, or stale result.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The feature MUST include a governed constitution amendment and dependent guidance
  updates establishing Pandas with ArcGIS GeoAccessor for small spatial workloads, DuckDB for
  larger tabular workloads, its spatial extension for larger spatial operations when needed,
  and on-disk DuckDB for persistent relational working databases instead of SQLite.
- **FR-002**: The amendment MUST explicitly resolve the current Principle II ArcPy-only geometry
  requirement and align Principle VIII and Technology Constraints. It MUST preserve sparse
  correctness, explicit semantics, deterministic representatives, immutable publication,
  resumability, isolated workers, and bounded execution. Governance changes MUST be versioned
  with rationale and cutover impact through a separate constitution-update workflow, including
  the pull request required by current Governance, before conflicting implementation begins.
  Local amendment preparation alone does not satisfy this prerequisite.
- **FR-003**: The builder MUST apply the engine policy to existing AOI, edge, H3 polygon,
  representative, and candidate geometry workflows, not just newly added helpers. ArcPy MUST
  remain available for Network Analyst, network location, source adapters, and geoprocessing
  capabilities that require it; no rewrite of Network Analyst solving is included.
- **FR-004**: Small spatial tabular workloads MUST use the ArcGIS GeoAccessor, not GeoPandas.
  ArcGIS-backed spatial work MUST use the approved ArcGIS geometry capability rather than
  silently falling back to Shapely/pyproj. DuckDB Spatial's internal implementation is not
  prohibited by this restriction on direct application dependencies and fallback paths.
- **FR-005**: Engine selection MUST use an explicit, versioned, deterministic resource policy
  with a resolved memory budget and working-set estimate, including intermediates. An estimate
  at or below the budget qualifies for the small path; a larger or unknown estimate selects the
  bounded large-data path. Selection MUST precede complete spatial-table materialization.
- **FR-006**: Large-data processing MUST impose memory, batch, and temporary-disk controls and
  MUST NOT require loading the full dataset into Pandas to estimate, transfer, or query it.
  H3 cover generation and retained candidate/scope ID collections MUST also remain bounded
  before any complete-collection allocation, not merely during subsequent sorting or transfer.
  Exceeded limits MUST fail explicitly without truncation or successful partial publication.
- **FR-007**: Resolved engine choices, policy version, budgets, estimate/provenance, engine
  versions, and behavior-affecting spatial settings MUST be logged and recorded in run metadata.
  Resume MUST reuse recorded policy/settings or reject incompatible explicit overrides; it MUST
  NOT silently change behavior based on a fresh resource snapshot. Behavior-affecting changes
  MUST participate in compatibility fingerprinting. Reusable-result compatibility MUST include
  relevant producing-engine decisions, not the whole run's stage inventory; adding unrelated
  stages during AOI expansion MUST NOT alone invalidate completed compatible work.
- **FR-008**: Spatial paths MUST preserve existing CRS validation, explicit reprojection, units,
  intersection semantics, geodesic distance semantics, and deterministic tie-breaking.
  Acceptance tolerances MUST be declared before comparison and MUST NOT excuse different
  cell membership, directed keys, classifications, or representative selection.
  Where DuckDB Spatial lacks a required operation or equivalent semantics, the large-data path
  MUST delegate only that operation to bounded GeoAccessor/ArcPy batches. Such delegation MUST
  be explicit in logs and run metadata, stay within the resolved memory budget, and preserve
  DuckDB-led large-data filtering/orchestration. If the delegated capability is unavailable or
  cannot satisfy the budget or semantics, execution MUST fail explicitly without partial success.
- **FR-009**: H3 identities MUST remain validated exact integers throughout both paths, storage,
  serialization, and publication. Required H3 columns MUST retain explicit 64-bit integer types;
  null, bool, float, and textual aliases MUST be rejected at identity boundaries. Existing
  uint64 publication fields and exact values above `2^53` MUST be preserved.
- **FR-010**: All persistent relational builder working databases, including the OD ledger,
  MUST use on-disk DuckDB. No SQLite runtime persistence or automatic SQLite fallback is allowed.
  Transient query databases MAY be in memory. Existing immutable result parts, Parquet/GeoParquet
  publication, and JSON manifests are not relational databases and MUST NOT be replaced merely
  to satisfy this requirement.
- **FR-011**: The durable database MUST preserve Feature 003 work identity, expected logical keys,
  legal state transitions, attempts, retry policy, failure evidence, lease expiry/reclaim,
  fencing, invalidation, transaction atomicity, and restart reconciliation. The backend change
  MUST NOT weaken unique logical-key claims or immutable-part commit acceptance.
- **FR-012**: The coordinator MUST own the authoritative database's read-write access. Spawned
  workers MUST exchange immutable assignments/results without opening that database.
  Conflicting coordinator ownership MUST be rejected explicitly; the feature MUST NOT introduce
  a server database or multi-process database-write policy.
- **FR-013**: Existing SQLite working databases MUST be refused without migration, deletion,
  overwrite, adoption, or source-file mutation, including sidecars. Operators MUST receive
  instructions to select a separate fresh DuckDB location. Fresh work MUST not claim old-state
  reuse; compatible new-state restart and AOI reuse MUST remain supported.
- **FR-014**: New durable state MUST identify its engine and format version, validate compatibility
  before adopting work, and reject corrupt or incompatible state explicitly. Legacy inspection
  MUST not mutate the source. Historical publications MUST remain unchanged.
- **FR-015**: Non-spatial H3 math, planning, ledger, manifest, and validation MUST remain importable
  and testable without ArcPy or an ArcGIS spatial dependency. Non-spatial DuckDB use MUST not
  load or require the spatial extension. Spatial prerequisites MUST be checked only where needed,
  with actionable errors and no silent geometry-engine substitution.
  The spatial extension MUST be provisioned during environment setup; builds MUST only load an
  already installed extension and MUST NOT download/install it at runtime. Missing-extension
  tests MUST verify zero download attempts as well as the actionable failure.
- **FR-016**: Acceptance coverage MUST compare both spatial paths with pre-change reference
  expectations; test exact integer round-trips across resolutions 0-15; interrupt every lifecycle
  boundary; and cover lease reclaim, stale rejection, competing coordinators, invalid staged
  output, disk/resource failure, legacy refusal, and compatible new-state AOI expansion.
- **FR-017**: Plans and implementation MUST synchronize operator/configuration/API guidance and
  directly affected feature/design constraints with the amended constitution, while preserving
  historical decisions as history. Any dependency additions MUST be explicitly flagged and
  justified. No unrelated dependency upgrades or new spatial fallback stack are included.

### Key Entities

- **Engine Decision**: Workload category, size/working-set estimate, budget, selected execution
  path, policy version, and provenance recorded for reproducibility.
- **Spatial Workload**: AOI/edge/cell records with declared CRS, exact H3 identities, operation
  semantics, bounded batches, and deterministic representative rules.
- **Durable Build Database**: A versioned on-disk working database owned by the coordinator,
  retaining work identity, lifecycle evidence, logical-key claims, and committed-part references.
- **Compatibility Record**: Input/policy/format evidence determining whether completed work can
  be reused without changing logical results.
- **Legacy Working State**: Existing SQLite files and associated sidecars preserved unchanged
  and excluded from automatic adoption.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of the agreed spatial conformance fixtures, both execution paths preserve
  the reference eligible cells, directed keys, classifications, and representative choices;
  numerical quantities meet predeclared tolerances. This includes a fixture requiring recorded,
  bounded ArcGIS delegation from the large-data path.
- **SC-002**: All identity samples across resolutions 0-15, including pentagons, greatest valid
  samples, and values above `2^53`, round-trip exactly through every applicable boundary, with
  zero accepted float/text/null identity substitutions.
- **SC-003**: Resource-policy tests cover below-budget, equal-budget, above-budget, and unknown
  estimates. The larger-than-budget fixture completes with zero full-input in-memory table
  materializations and measured controlled allocations within the declared acceptance budget.
- **SC-004**: Recovery at every lifecycle boundary produces zero missing committed results and
  zero duplicate logical keys; 100% of stale-worker and conflicting-owner attempts are rejected.
- **SC-005**: Every legacy cutover fixture is refused with fresh-build guidance and zero changed
  source bytes/files; compatible new-state restart and expansion reuse exactly the expected
  completed work.
- **SC-006**: Every engine decision and prerequisite/resource failure is visible in logs and,
  where a run exists, durable run evidence. No failure fixture exposes an authoritative partial
  dataset or success-shaped empty result.

## Assumptions

- This invocation produces a specification, not a production-code change or an enacted
  constitution amendment. The amendment is a prerequisite deliverable for implementation.
- The user confirmed that eligibility geometry is included in the new policy, with ArcPy retained
  for Network Analyst and capabilities requiring it.
- The user confirmed a pre-alpha, fresh-ledger cutover: no SQLite migration or historical rewrite.
- Exact 64-bit support is a requirement to validate at boundaries, not a guarantee conferred by
  selecting Pandas, GeoAccessor, or DuckDB. Efficiency is motivation, not an unmeasured speed claim.
- Memory budgets, estimate methods, tolerances, and instrumentation are design decisions for the
  plan; their configured values and acceptance fixtures must be fixed before implementation tests.
  Existing resource-limit semantics remain in force unless explicitly amended.
- Arrow/PyArrow remains approved for schemas, typed interchange, file I/O, and metadata validation;
  plain records remain suitable for non-spatial control/lifecycle logic.
- Dependencies and extension availability must be verified against the supported ArcGIS Pro
  environment. A new environment/package requirement must be called out, not assumed installed.
- Features 001-006 supply the existing behavioral and external publication contracts. This
  feature changes processing/storage engines, not candidate policy, outcome policy, concurrency
  ceilings, representative policy, or the published schema.
- Shared solver contract adoption remains a separate release gate; this builder-only engine
  change does not claim solver approval or change the solver's implementation.
