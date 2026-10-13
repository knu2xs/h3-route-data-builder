# Implementation Plan: Sparse OD Candidates

**Branch**: `002-sparse-od-candidates` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-sparse-od-candidates/spec.md`

## Summary

Plan directed OD pairs from Feature 001 solvable cells for AOI-only and AOI-to-surrounding
builds. Use ArcPy for the AOI expansion, polygon membership, and representative-point distance
operations. Keep deterministic pair planning, endpoint checks, prefilter decisions, and metrics
portable and importable without ArcPy. Send only retained non-self logical pairs to Feature 003's
durable ledger; resolve origin self-pairs directly at zero cost. Treat the representative-distance
error bound as explicit policy: when it is absent, retain pairs rather than apply an implicit
tolerance. Feature 003 owns route solving and durable state; its post-solve handoff must classify
actual network costs against the configured cutoff before a result can be committed or published
as qualifying output.

## Technical Context

**Language/Version**: Python 3.13 in ArcGIS Pro; project minimum Python 3.11.

**Primary Dependencies**: ArcPy / Network Analyst for spatial and route operations; H3 v4 for
canonical cell IDs; existing project utilities and pytest. No new dependency is planned.

**Storage**: Candidate planning is in-memory and bounded by resolved execution limits. Durable
work state and immutable route results remain owned by Feature 003 and live outside worker scratch
geodatabases. Feature 002 does not choose a new ledger storage engine.

**Testing**: pytest. Pure candidate and reconciliation rules are tested without ArcPy; geometry
scope and the Feature 003 post-solve cutoff handoff use ArcPy-marked integration tests and
synthetic fixtures. Acceptance tests also verify structured log/count reconciliation and
manifest-restored execution policy.

**Target Platform**: ArcGIS Pro / `arcgispro-py3`; portable candidate rules remain usable in
non-ArcPy test environments.

**Project Type**: Python package and ArcGIS Pro geoprocessing pipeline.

**Performance Goals**: No fixed sparsity ratio or runtime target. Bound destination expansion,
pair enumeration, and per-origin destination batches by resolved execution limits; report exact
scope, pruning, ledger, and solve counts.

**Constraints**: Keep ArcPy imports within network/geoprocessing operations. Use declared spatial
references and Feature 001's fixed WGS 84 / EPSG:4326 geometry contract; use geodesic meters for
spatial distances and expansion, with no configurable analysis CRS. Retain pairs when a valid
conservative lower bound is unavailable. The configured measurement-error bound is subtracted
from measured geodesic separation; if absent, retain candidates without pruning. Apply the
network cutoff to actual solved network costs in the Feature 003 handoff, never estimates.
Candidate policy, resolved execution-limit provenance, and inference-policy version are supplied
to Feature 003 for fingerprinting and manifest persistence; resume restores saved values.

**Scale/Scope**: Operate on Feature 001 solvable cells, respecting the existing resource-aware
execution policy and total solvable-cell cap. Process directed origin/destination products in
bounded batches; fail incomplete rather than truncate on any configured limit.

**Candidate policy provenance**: `network.prefilter_distance_error_bound_m` is optional and
defaults to `null`, which disables pruning by an unbounded measured distance while retaining all
otherwise eligible candidates. When set, the value must be a justified finite nonnegative upper
measurement-error bound. Record it with cutoff/reach inputs in Feature 003's behavior fingerprint
and run manifest.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Before Research

- **I. Explicit semantics**: PASS. AOI membership policy, cutoff, units, maximum-speed bound, and
  deterministic ordering are explicit inputs and are recorded with the run policy.
- **II. Builder ArcPy geometry boundary**: PASS. ArcPy owns AOI and H3 polygon geometry, geodesic
  spatial expansion, and representative-point distance operations in WGS 84 / EPSG:4326. Pair
  identity, endpoint validation, and ledger reconciliation remain non-spatial.
- **III. Sparse correctness**: PASS. Only Feature 001 `solvable` endpoints enter the candidate
  plan.
- **IV. Immutable reproducibility**: PASS. Candidate policy inputs are part of the behavior
  fingerprint; output publication remains immutable and is outside this feature's scope.
- **V. Idempotent resumability**: PASS. Pair keys are deterministic; compatible committed facts
  are reused and missing/invalidated keys are planned once.
- **VI. Approximation transparency**: PASS. Straight-line separation is used only as a proven
  conservative prefilter bound, never persisted as network cost.
- **VII. Bounded execution**: PASS. Scope construction and candidate batches use resolved limits;
  limit overflow fails incomplete rather than silently omitting work.
- **VIII. Interoperability**: PASS. No change to the shared OD fact schema is required.
- **IX. Observable operation**: PASS only with the required structured candidate logs and
  reconciliation of scope, pruning, ledger actions, solves, and cutoff outcomes; implementation
  tasks make these observable behaviors explicit.
- **X. Testable contracts**: PASS. Portable and ArcPy integration acceptance tests are planned.
- **XI. Serial reference path first**: PASS. Candidate ordering and planning are deterministic;
  parallelism is not introduced by this feature.
- **XII. Deterministic representatives**: PASS. Candidate planning consumes, and does not alter,
  Feature 001's deterministic representatives.
- **XIII. Durable work lifecycle**: PASS. Ledger lifecycle, leases, staging, and commits remain
  Feature 003 responsibilities; this plan defines the expected logical-key handoff.
- **XIV. Isolated workers**: PASS. Worker execution strategy is unchanged.
- **XV. Publish atomically**: PASS. Publication is unchanged and remains downstream.
- **XVI. Complete Pro tool documentation**: PASS. No new exposed toolbox class or parameter is
  currently required by this internal planning feature.
- **XVII. Resource-aware execution limits**: PASS only when candidate execution reuses resolved
  values, logs each value and source, fingerprints the candidate policy, persists provenance in
  Feature 003's manifest, and restores the same values on resume; tasks require these checks.

No pre-research gate violations.

## Project Structure

### Documentation (this feature)

```text
specs/002-sparse-od-candidates/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── candidate-planning.md
└── tasks.md              # Created by /speckit-tasks
```

### Source Code (repository root)

```text
src/h3_route_data_builder/
├── network/
│   ├── geometry.py       # ArcPy AOI expansion and representative distances
└── od/
    ├── candidates.py     # Portable directed pair planning and metrics
    └── models.py         # Candidate scope, pair, and summary records

testing/
├── test_od_candidates.py
├── test_od_candidate_geometry.py
└── test_od_candidate_ledger.py
```

**Structure Decision**: Keep pure ordered-pair rules separate from ArcPy geometry operations,
matching the existing division between `eligibility/` and `network/`. The ledger handoff is a
contract to Feature 003; this feature does not add a competing ledger implementation.
Feature 003 remains responsible for invoking the route solver, persisting durable state, and
writing its manifest. It must call the candidate result-classification boundary with actual
solved costs before validating or committing qualifying output. Candidate acceptance tests cover
this handoff with a synthetic solver/ledger adapter without introducing a second solver or ledger.
The handoff also carries the resolved execution limits and sources, execution-policy version, and
candidate-affecting cutoff and error-bound values so Feature 003 can fingerprint them and restore
them unchanged on resume.

## Phase 0: Research

Completed in [research.md](research.md). The project constitution, Feature 001/003 design notes,
shared data contract, configuration, existing ArcPy geometry module, and resource-limit policy
resolve the applicable technical choices; no external package or service choice is introduced.

## Phase 1: Design & Contracts

- [Data model](data-model.md) defines the solvable endpoint, AOI scope, directed pair, prefilter
  disposition, ledger reconciliation, and summary metrics.
- [Candidate planning contract](contracts/candidate-planning.md) defines the internal boundary
  from candidate planning to Feature 003's work ledger. No new public API or OD fact schema is
  required.
- [Quickstart validation guide](quickstart.md) lists the end-to-end scenarios and acceptance
  commands for implementation.

### Post-Design Constitution Check

- **I-III, V-VII, IX-XIII, XVII**: PASS. Scope, conservative pruning, deterministic identity,
  ledger reconciliation, bounded batches, manifest-restored policy provenance, structured logs,
  and metrics are explicit and testable.
- **II**: PASS. ArcPy geometry work is isolated; portable candidate logic does not import ArcPy.
- **IV, VIII, XV**: PASS. Fingerprinting includes candidate-affecting policy; the shared output
  schema and atomic publication are unchanged.
- **XI, XIV**: PASS. This feature defines deterministic serial behavior and does not add parallel
  execution.
- **XVI**: PASS. No toolbox surface changes are in scope.

No post-design gate violations. Complexity tracking is not applicable.
