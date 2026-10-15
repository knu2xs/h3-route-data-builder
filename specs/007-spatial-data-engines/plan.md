# Implementation Plan: Spatial Data Engine Standardization

**Branch**: `main` (no Git branch created) | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-spatial-data-engines/spec.md`

## Summary

Replace the builder's small spatial-table processing with Pandas/ArcGIS GeoAccessor and its
large-data processing with bounded DuckDB queries, loading the installed Spatial extension only
for spatial operations. Replace SQLite working persistence with coordinator-owned, on-disk DuckDB.
Keep exact integer H3 identities, fixed geometry/candidate semantics, isolated Network Analyst
workers, immutable result parts, and current publication schemas.

The user authorized a fresh-state pre-alpha cutover, not migration. SQLite files and sidecars are
refused without modification. Unsupported/non-equivalent large-data geometry operations delegate
to explicitly recorded, bounded ArcGIS batches. Builds never download extensions.

**Implementation entry gate:** complete a separate, explicit constitution-update workflow for
2.0.1 to proposed 3.0.0, including the pull request required by current Governance, before
conflicting geometry implementation begins. Preparing local amendment text alone does not
satisfy this gate. Record the amendment PR and enacted version; do not infer completion from
this plan or create a PR without authorization. This plan does not enact the amendment or
define additional approval rules beyond existing Governance.

## Technical Context

**Language/Version**: Python minimum 3.11; configured ArcGIS Pro interpreter is Python 3.13.13.

**Primary Dependencies**: Existing DuckDB 1.3.2, PyArrow 22.0.0, H3 4.5.0 and ArcPy/Network Analyst.
Local Pandas 3.0.0 and ArcGIS API for Python 2.4.3.1 provide the small-data path. Do not upgrade
these as a side effect. Local function probes, rather than current online documentation alone,
determine capabilities of DuckDB 1.3.2.

**Dependency additions requiring review**: add a `spatial` optional dependency group in
`pyproject.toml` declaring `pandas>=2.0` and `arcgis>=2.4.3.1`, because new lazy spatial imports
must have a declared install path without burdening portable ledger consumers. Add explicit
`pandas>=2.0` to `environment.yml`; `arcgis` already exists there. Document the supported tested
version matrix, not a promise that every future version works. Spatial is a DuckDB extension,
not a new Python package. No GeoPandas, direct Shapely/pyproj, server, or monitoring dependency.

**Storage**: Native on-disk DuckDB ledger format 3 with `UBIGINT` H3 endpoints, outside worker
scratch. Optional DuckDB scratch databases/Arrow batches for bounded spatial intermediates.
JSON run manifests and immutable Parquet/GeoParquet files remain. Eligibility Arrow schema 2,
dataset/cell/fact 2.0.0, and GeoParquet 1.1.0 remain unchanged.

**Testing**: Existing pytest, real subprocess/spawn tests, synthetic ArcGIS geometry fixtures,
Arrow/DuckDB exactness tests, Windows process-memory observations via standard-library ctypes,
and current toolbox/real-network tests. No new test runner. Spatial tests require the spatial
environment; portable tests actively block ArcGIS/ArcPy imports.

**Target Platform**: Local Windows ArcGIS Pro clone; portable non-spatial Python modules remain
usable without ArcGIS. Authoritative DuckDB files reside on local storage with reliable locks,
not a multi-host/network-file coordination service.

**Project Type**: Python library with ArcGIS Pro toolbox entry point.

**Performance Goals**: No speedup or latency promise. Demonstrate no full-input spatial-table
materialization on the large path, bounded conversions/queries, exact logical equivalence, and
reliable recovery. Policy and measurable resource acceptance are defined in the contract.

**Constraints**: Single coordinator owns all authoritative database access while open, including
reads. Serialize its transactions; workers carry no connection or database path. Memory controls
cover shared spatial processing, not a false hard cap on ArcGIS Pro or solver processes.
No runtime extension installation, silent engine fallback, state migration, or historical rewrite.

**Scale/Scope**: Existing bounded AOI/edge/cell eligibility, candidate geometry, ledger and
publication handoff. Principle XVII execution limits and Feature 005 worker/preparation ceilings
remain unchanged. New engine policy version 1 adds memory and spill controls, not new candidates.

## Constitution Check

*Pre-research and post-design review against constitution 2.0.1.*

| Principle | Pre-design assessment | Post-design disposition |
|---|---|---|
| I Explicit semantics | Applicable | PASS: configured policy, units, tolerances and manifest/fingerprint evidence. |
| II ArcPy geometry boundary | CONFLICT: authorizes ArcPy only for eligibility geometry | BLOCKED pending separate governed amendment: proposed 3.0.0 is not enacted; conflicting code cannot begin before the gate above is satisfied. |
| III Sparse correctness | Non-negotiable | PASS: exact predicates, conservative prefilters and boundary/touch fixtures; no false exclusions. |
| IV Immutable reproducibility | Applicable | PASS: engine versions/settings enter compatibility; old publications unchanged. |
| V Idempotent resumability | Applicable | PASS: same logical work IDs, format-3 database, transaction/restart acceptance. |
| VI Approximation transparency | Applicable | PASS: no estimated distance becomes network cost. |
| VII Bounded execution | Applicable | PASS: byte-budgeted streaming, fan-out-safe processing, spill limits and explicit failures. |
| VIII Interoperability | Expand approved engine guidance | PASS AFTER AMENDMENT: GeoAccessor/DuckDB, Arrow interchange retained, no GeoPandas. |
| IX Observable operation | Applicable | PASS: engine decisions, delegation, resource failures and work counts recorded. |
| X Testable contracts | Applicable | PASS: FR/SC matrix in quickstart; exactness/recovery/resource contracts. |
| XI Serial reference first | Existing reference retained | PASS: compare both engines and serial/parallel outcomes against fixed baseline. |
| XII Representatives | Preserve deterministic selection | PASS: delegate geodesic/nearest/source-measure operations to bounded ArcGIS. |
| XIII Durable lifecycle | Engine replacement must preserve semantics | PASS: coordinator transactions and fencing; same transitions, no worker writes. |
| XIV Isolated workers | Existing probe/fallback retained | PASS: no database handles/paths in worker payloads; same worker ceilings. |
| XV Atomic publication | Preserve contract | PASS: database parts are transactionally committed; publication still stages/validates/_SUCCESS. |
| XVI Pro documentation | Operator-visible behavior changes | PASS: update XML help, toolbox descriptions and reader tests; verify Pro UI during implementation. |
| XVII Resource limits | Preserve policy-1 formulas | PASS: engine policy is additive, saved decisions reused; never silently recompute on resume. |

No shared solver principle is weakened. The proposed amendment redefines a builder-specific
principle and therefore merits MAJOR 3.0.0, not a patch. The PR must document rationale, cutover,
and affected guidance. Approval is not inferred from creating this plan.

## Project Structure

### Documentation (this feature)

```text
specs/007-spatial-data-engines/
    spec.md
    plan.md
    research.md
    data-model.md
    quickstart.md
    contracts/
        spatial-data-engines.md
        constitution-amendment.md
    tasks.md                       # generated later by /speckit-tasks
```

### Source Code (repository root)

```text
.specify/memory/constitution.md     # amendment before conflicting implementation
AGENTS.md                          # canonical guidance, not hand-edited generated copies
config/config.yml                  # data_engines settings
pyproject.toml                      # reviewed spatial extra
environment.yml                    # explicit pandas development dependency
src/h3_route_data_builder/
    eligibility/
        data_engines.py             # new portable policy/decision models and resolution
        engine.py                  # existing evidence semantics, streaming integration
        fingerprint.py
        limits.py                  # reuse resource snapshots; preserve existing formulas
    network/
        spatial.py                 # new lazy GeoAccessor/DuckDB spatial adapters
        geometry.py                # existing validation/projection/candidate helpers
        eligibility.py             # stream source cursor, no unbounded edge list
        representatives.py         # bounded exact ArcGIS representative evaluation
        workflow.py                # resolve/restore policy before materialization
    od/
        ledger.py                  # DuckDB implementation, unchanged constructor/method semantics
        execution.py               # coordinator ownership and deterministic close
        preparation.py             # no live DB in payloads
    sql/
        ledger_schema.sql          # externalized format-3 schema
        spatial_cell_edge_pairs.sql
        spatial_scope_membership.sql
        ...                        # other nontrivial/parameterized statements, no inline f-strings
testing/
    test_data_engines.py            # new portable policy and metadata tests
    test_spatial_engines.py         # new spatial equivalence/resource/delegation tests
    test_od_ledger.py               # port backend assertions; preserve lifecycle tests
    test_od_execution*.py
    test_eligibility_*.py
    test_network_eligibility.py
    test_od_candidate_geometry.py
    test_publication_*.py
    test_real_network_dataset.py
arcgis/
    README.md
    h3_route_data_builder.pyt
    h3_route_data_builder.GeometryEligibilityTool.pyt.xml
docsrc/mkdocs/
    api.md
    configuration.md
    design/                        # active engine guidance and explicit historical supersession
```

**Structure Decision**: Reuse the existing modules. Add only one portable policy module and one
spatial adapter module; no generic backend registry or pluggable SQLite compatibility layer.
Keep SQL assets behind the existing `load_sql()` helper. New tests mirror these responsibilities.

## Phase 0: Research Outcome

See [research.md](research.md). Local probes established exact uint64 Pandas/Arrow/DuckDB transfer,
GeoAccessor retention of an integer identity, ArcPy availability, installed Spatial loading with
automatic extension installation/loading disabled, and rollback on DuckDB 1.3.2. These probes
are feasibility evidence, not the full geometry or crash acceptance suite.

Key decisions:

- Use one long-lived connection per live ledger owner, not SQLite's per-operation connections.
- Keep committed part payloads inside the database transaction, matching current behavior.
- Use `UBIGINT`, typed Python model validation, explicit transactions, sequence event IDs,
  and materialized typed row mappings instead of SQLite row factories/PRAGMAs/autoincrement.
- Native file locks plus an in-process canonical-path ownership guard reject a second live
  ledger. Add deterministic `close()` and context-manager support without changing existing
  public argument lists. Update all in-repository reopen sites to release ownership explicitly.
- Use geometry-aware conservative byte estimates and incremental Arrow/WKB transfer. Unknown
  estimates choose DuckDB; a single geometry exceeding the batch allocation fails clearly.
- Do not rely on planar degree distances, spatial-index availability, or recent functions not
  present in DuckDB 1.3.2. Delegate exact geodesic/nearest representative work.

## Phase 1: Design and Delivery Order

1. **Governance and baseline**: prepare the proposed amendment with a Sync Impact Report in a
   separate constitution workflow and complete the required PR governance before conflicting
   implementation; synchronize canonical guidance and active design constraints with it.
   Capture known pre-existing logging failures
   separately and freeze geometry, directed-key, representative, and outcome fixtures.
2. **Portable policy**: add validated settings/decision serialization and boundary tests first.
   Persist a run-envelope `engine_metadata_version=1`; missing metadata in old working runs
   requires a fresh output root, not adoption or relabeling.
3. **Durable DuckDB cutover**: replace SQLite end-to-end, preserving method semantics and adding
   explicit lifetime ownership. Test transactions, reopen, crash/WAL replay, lease reclaim,
   stale rejection, invalidation/recommit, immutable parts, and unchanged legacy files.
4. **Small spatial reference**: use GeoAccessor spatial tables with explicit `uint64` H3 columns
   and ArcGIS geometry execution; preserve exact dimensional intersection and nearest rules.
   Index/transport labels may be opaque integers but are never H3 values in float fields.
5. **Large spatial execution**: stream sources into typed DuckDB batches, filter/join and
   reconcile without `list(edges)` or fetching all pairs. Stream result pairs grouped by cell,
   reduce deterministic representative candidates incrementally, and spill intermediate data.
   Apply the same rule to candidate geometry and AOI preparation, not only eligibility joins.
6. **Integration/acceptance**: restore saved policies before source materialization, propagate
   semantic compatibility into OD/publication evidence, preserve public outputs and worker
   policy, synchronize toolbox/operator guidance, run targeted then full validation.

Contracts: [engine and storage interface](contracts/spatial-data-engines.md) and
[proposed amendment](contracts/constitution-amendment.md).
Entities: [data-model.md](data-model.md). Validation: [quickstart.md](quickstart.md).

### Compatibility and Public API Boundaries

- Retain existing public positional/keyword arguments. Engine settings come from existing
  `config_node`/configuration inputs; internal helpers may receive a resolved decision explicitly.
- `ODLedger(database_path, max_attempts=3)` remains; add `close()`, `__enter__`, `__exit__`.
  No destructor is the primary release mechanism. All coordinator entry points close on error.
- Ledger format becomes 3 with engine `duckdb`; the integer work-ID encoding remains 2 because
  logical work identity is unchanged. Compatibility payload gains engine-policy metadata;
  do not claim reuse across engine/settings versions merely because keys match.
- Eligibility table/state schema 2 and external dataset versions remain unchanged; run envelopes
  must carry engine metadata version 1 and are incompatible without it.
- Publish engine evidence in existing manifest policy/provenance slots, not new OD fact columns.
  Trace the actual handoff in `od/candidates.py`, `od/results.py`, and `publication/publish.py`
  as well as `network/workflow.py`; no disconnected metadata-only path.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Principle II currently mandates ArcPy-only eligibility geometry | User explicitly requested GeoAccessor/DuckDB eligibility and confirmed the scope | Keeping ArcPy-only eligibility contradicts the requested standardization; amend to 3.0.0 before code, not a silent exception. |

Post-design review: the exception is bounded and explicit; no other constitutional violation is
accepted. Implementation is gated on the amendment; this planning-only change introduces none of
the conflicting runtime behavior.
