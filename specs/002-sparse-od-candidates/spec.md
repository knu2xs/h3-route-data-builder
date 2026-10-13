# Feature Specification: Sparse OD Candidates

**Feature Branch**: `[002-sparse-od-candidates]`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "Create Builder Feature 002: Sparse OD Candidates. Read the shared constitution and builder Features 001 and 003 first. Specify how to form directed OD candidate pairs from solvable cells for AOI-only and AOI-to-surrounding builds. Define which cells qualify as inside the AOI and how the surrounding destination area is bounded. Require deterministic pair keys, self-pairs that do not invoke a network solve, and a conservative straight-line prefilter that cannot exclude a route meeting the configured network cutoff. Require the actual cutoff to be applied after solving. Define how candidate pairs connect to Feature 003’s work ledger so only missing or invalidated pairs are scheduled. Specify measurable validation for false-negative prefiltering, unsolvable endpoints, directionality, and pruning metrics; do not require a fixed sparsity ratio. Keep implementation details out unless needed to make these contracts testable."

## Clarifications

### Session 2026-10-12

- Q: In AOI-to-surrounding mode, should a destination qualify when its network representative is inside the expanded AOI, or when any part of its H3 cell polygon intersects that area? → A: A destination qualifies when any part of its H3 cell polygon intersects the expanded AOI.
- Q: In AOI-to-surrounding mode, should cells that are destinations only also get a self-pair with themselves? → A: Only cells in the origin set (the in-AOI solvable cells) get self-pairs.
- Q: For AOI-to-surrounding builds, how should the maximum offset of in-AOI origin representatives be measured when expanding the AOI? → A: Use the greatest straight-line distance from any in-AOI origin representative to the AOI geometry, measured in the configured distance units; Feature 001 fixes spatial measurements to geodesic meters in WGS 84 / EPSG:4326.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate AOI-Only Candidates (Priority: P1)

As a builder operator, I need a complete directed candidate set from the network-solvable cells
inside an AOI so that every eligible origin-to-destination route can be evaluated without planning
work for cells that cannot be solved.

**Why this priority**: AOI-only candidate generation is the smallest useful build mode and defines
the pair semantics shared by surrounding-area builds.

**Independent Test**: Given a small AOI and a known set of solvable cells, compare the generated
logical pair keys to the expected directed Cartesian product, including self-pairs.

**Acceptance Scenarios**:

1. **Given** solvable cells whose canonical H3 polygons intersect the AOI, **When** an AOI-only
   build forms its scoped pair universe, **Then** each ordered pair in that set appears exactly
   once, including one self-pair for each cell, before non-self pairs are evaluated by the
   prefilter.
2. **Given** cells that do not intersect the AOI or are not solvable, **When** an AOI-only build
   forms candidates, **Then** none of those cells appears as an endpoint.
3. **Given** a self-pair, **When** the candidate is handled, **Then** it is recorded with zero
   network cost without invoking a network solve.

### User Story 2 - Include Bounded Surrounding Destinations (Priority: P1)

As a builder operator, I need origins from inside the AOI and destinations from a bounded
surrounding area so that routes leaving the AOI are represented without searching an unbounded
network.

**Why this priority**: The surrounding build mode is the principal extension beyond AOI-only
coverage, and its boundary must not discard any destination reachable within the configured
network cutoff.

**Independent Test**: For a small AOI and finite distance or time cutoff, verify the origin set,
expanded destination scope, directed pairs, and inclusion of destinations at the cutoff reach.

**Acceptance Scenarios**:

1. **Given** an AOI with solvable cells and a finite configured cutoff, **When** an
   AOI-to-surrounding build forms candidates, **Then** origins are the in-AOI solvable cells and
   destinations include solvable cells whose H3 polygons intersect the cutoff-derived expanded
   area.
2. **Given** a destination at exactly the conservative reach boundary, **When** candidates are
   formed, **Then** it is retained for straight-line evaluation.
3. **Given** no defensible spatial reach bound for the configured cutoff, **When** the build is
   validated, **Then** it fails clearly before scheduling candidates rather than silently
   truncating the destination scope.

### User Story 3 - Reconcile Candidates with Resumable Work (Priority: P1)

As a builder operator, I need each candidate to reconcile with the resumable OD work ledger so
that valid completed pairs are reused and work is not duplicated after interruption or AOI
expansion.

**Why this priority**: Candidate planning at build scale must preserve Feature 003's
idempotency and avoid repeating expensive network solves.

**Independent Test**: Seed a ledger with valid committed, absent, invalidated, and in-progress
logical pairs; verify which pairs are newly planned and which existing work is reused or resumed.

**Acceptance Scenarios**:

1. **Given** a candidate with valid compatible committed evidence, **When** planning reconciles
   against the ledger, **Then** it is reused and is not scheduled again.
2. **Given** a candidate with no ledger evidence or explicitly invalidated evidence, **When**
   planning reconciles against the ledger, **Then** it is planned exactly once.
3. **Given** an existing uncommitted or retryable ledger item, **When** planning resumes, **Then**
   the existing Feature 003 lifecycle is continued without creating a duplicate work item.

### Edge Cases

- A cell polygon that only touches the AOI boundary is inside when the configured intersection
  policy is inclusive; the configured policy governs other boundary cases.
- A zero-solvable-cell scope produces no pairs and reports zero-valued counts without a solve.
- A straight-line distance equal to the conservative reach is retained, not pruned.
- Reverse pairs `(A, B)` and `(B, A)` are distinct; a self-pair `(A, A)` is emitted once.
- A missing or non-solvable endpoint is rejected from candidate keys and reported, never sent to
  the ledger or network solver.
- Existing terminal ledger failures are not automatically scheduled again; they remain terminal
  unless explicitly invalidated.
- A time cutoff without a documented maximum permitted speed or an equivalent proven conservative
  spatial reach bound is invalid for candidate generation.
- Duplicate cell inputs or repeated enumeration must not create duplicate logical pair keys.
- An invalid, negative, non-finite, or unit-incompatible cutoff fails validation before planning.
- Exceeding a configured candidate/build limit fails the build as incomplete; it must not silently
  omit candidate pairs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Candidate generation MUST use only Feature 001 cells marked `solvable` and carrying
  valid deterministic network representatives.
- **FR-002**: A solvable cell MUST qualify as inside the AOI when its canonical H3 polygon
  intersects the AOI under the configured intersection policy. A boundary touch counts when that
  policy is inclusive.
- **FR-003**: In AOI-only mode, the origin and destination sets MUST be the same set of in-AOI
  solvable cells. The unfiltered scoped pair universe MUST include every ordered pair from that
  set exactly once. The prefilter MAY remove eligible non-self pairs from the solve set as
  specified below.
- **FR-004**: In AOI-to-surrounding mode, origins MUST be the in-AOI solvable cells. Destinations
  MUST be solvable cells whose canonical H3 polygons intersect the AOI expanded by a conservative
  reach radius plus the greatest geodesic distance in meters from any in-AOI origin representative
  to the nearest point on the AOI geometry (zero for a point within the AOI), consistent with
  Feature 001's WGS 84 / EPSG:4326 contract. The destination scope MUST include the AOI.
- **FR-005**: The cutoff-derived reach radius MUST be bounded and expressed in units compatible
  with representative-point separation. A distance cutoff MUST have explicit units and MUST be
  converted to meters. Spatial measurements and distance reach MUST use geodesic meters in WGS 84
  / EPSG:4326. For a distance cutoff, the reach MUST be at least the converted cutoff distance.
  For a time cutoff, it MUST be at least the cutoff time multiplied by a documented upper bound
  on permitted network speed, or be another documented spatial bound proven to cover every route
  meeting the cutoff. If neither bound is available, the build MUST fail before scheduling.
- **FR-006**: The candidate universe MUST contain directed pairs. Its logical key MUST be
  deterministic from the ordered origin and destination H3 identifiers, independent of input
  order; reversing endpoints MUST produce a distinct key. Dataset fingerprint and compatibility
  MUST be evaluated in the work ledger, separately from the logical pair identity.
- **FR-007**: Every cell in the origin set MUST produce exactly one self-pair. In AOI-only mode,
  this is every in-AOI solvable cell; in AOI-to-surrounding mode, this is every in-AOI solvable
  origin, not destination-only surrounding cells. A self-pair MUST be materialized with zero
  network cost and MUST NOT invoke a network solve.
- **FR-008**: Before a non-self pair is scheduled for solving, a straight-line lower bound between
  its network representative points MAY prune it only when that bound is strictly greater than a
  conservative spatial reach for the configured cutoff. A pair at or below the reach MUST be
  retained. The bound MUST be a conservative geodesic measurement in meters in WGS 84 /
  EPSG:4326 and MUST account for measurement error. Treat the configured
  `network.prefilter_distance_error_bound_m` as an upper bound on the absolute error of the
  representative-to-representative measurement, including coordinate precision, geodesic
  calculation, and unit conversion. The conservative lower bound is
  `max(0, measured_distance_m - prefilter_distance_error_bound_m)`. Pruning is allowed only when
  this lower bound is strictly greater than the cutoff-derived reach. The value MUST be finite,
  nonnegative, recorded with the run's candidate policy, and included in its behavior
  fingerprint. The configured value is the caller's assertion of a defensible upper bound; the
  software validates its form but cannot establish whether the assertion is accurate. A present
  but negative or non-finite value MUST fail validation before scheduling. If no defensible value
  is supplied, the prefilter MUST retain the pair and report it as retained because no valid
  measurement-error bound was available; it MUST NOT substitute an implicit tolerance. If the
  geodesic measurement itself is unavailable or invalid, retain the pair even when a configured
  error bound exists.
- **FR-009**: The prefilter MUST have zero false negatives: it MUST NOT remove any pair whose
  actual network result would meet the configured cutoff. When no valid lower bound is available,
  the prefilter MUST retain the pair rather than prune it.
- **FR-010**: The configured network cutoff MUST be applied to the actual network cost only after
  the route has been solved. Results meeting the cutoff are eligible for output; results exceeding
  it MUST be classified as cutoff-excluded and MUST NOT be published as qualifying OD costs.
  Feature 003 owns route solving and durable work lifecycle; its solve-result handoff MUST provide
  actual solved network costs to cutoff classification before a result can be validated,
  committed, or published as a qualifying OD fact. Candidate planning MUST NOT classify an
  estimated or prefilter distance as a solved network cost.
- **FR-011**: Every retained non-self candidate MUST reconcile to exactly one expected logical
  OD key in Feature 003's work ledger, assigned to the work unit for its dataset fingerprint,
  origin, and destination batch. Origin self-pairs MUST be accounted for as resolved zero-cost
  logical keys without being scheduled as route work. Prefilter-pruned pairs MUST be counted and
  excluded from the solve set.
- **FR-012**: Only retained non-self pairs absent from compatible ledger evidence or explicitly
  invalidated MUST be newly scheduled. Valid committed pairs MUST be reused. Existing
  uncommitted, retryable, or leased work MUST be resumed or reconciled under Feature 003 without
  creating duplicate work. Terminal failures MUST NOT be automatically rescheduled unless
  explicitly invalidated.
- **FR-013**: Candidate planning MUST reject any non-solvable or missing endpoint before ledger
  scheduling or network solving, and report the count and reason for rejected endpoint references.
- **FR-014**: The build summary MUST report scope pair count, self-pair count, non-self prefilter
  input count, pruned count, retained count, valid committed pairs reused, missing/invalidated
  pairs newly planned, recoverable work resumed, terminal failures left unscheduled, solved
  results, cutoff-excluded results, and retained pairs for which no valid distance measurement or
  configured error bound was available. The prefilter pruning ratio MUST be reported as pruned
  non-self pairs divided by non-self prefilter inputs, with zero when that denominator is zero.
  Counts MUST reconcile; no fixed minimum sparsity or pruning ratio is required.
- **FR-015**: Candidate evaluation and destination expansion MUST respect configured build limits.
  Reaching a limit MUST produce an explicit incomplete/failure outcome rather than silent
  truncation.
- **FR-016**: The run MUST log each resolved candidate execution limit with its value and source,
  and pass resolved values, sources, inference-policy version, cutoff reach inputs, and prefilter
  measurement-error bound into the Feature 003 run manifest and behavior fingerprint. A resumed
  run MUST reuse its recorded resolved limits and candidate-policy values; changed explicit
  overrides MUST identify a distinct run or fail clearly.

### Key Entities *(include if feature involves data)*

- **Solvable cell**: A canonical H3 cell that intersects an eligible traversable edge and has a
  valid deterministic network representative, as defined by Feature 001.
- **In-AOI cell**: A solvable cell whose canonical H3 polygon intersects the AOI under the
  configured intersection policy.
- **Directed OD candidate**: An ordered pair of solvable origin and destination cells, identified
  by a deterministic logical key; reverse direction is a separate candidate.
- **Conservative reach**: A finite upper bound on straight-line endpoint separation for any route
  that can meet the configured network cutoff.
- **Ledger work unit**: Feature 003's fingerprint/origin/destination-batch unit, which records the
  lifecycle and expected logical OD keys for resumable work.
- **Candidate metrics**: Reconciled counts describing scope, prefilter pruning, ledger reuse and
  planning, solving, and post-solve cutoff exclusions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Exhaustive reference tests for each supported cutoff type and prefilter bound report
  zero false-negative prunes, including routes whose actual cost equals the cutoff and simulated
  measurement errors up to the configured error bound. When the error bound is absent, no pair
  may be pruned on the basis of an unbounded measurement.
- **SC-002**: Candidate and ledger validation tests report zero non-solvable or missing endpoint
  identifiers in planned work, solved pairs, or qualifying outputs; every rejected endpoint
  reference is counted and classified.
- **SC-003**: Directionality tests produce exactly one key for each ordered pair, distinct keys
  for `(A, B)` and `(B, A)`, and exactly one zero-cost self-pair per in-AOI origin with zero
  network solves for self-pairs.
- **SC-004**: On test fixtures, every reported scope, self-pair, prefilter, reuse, planning, solve,
  and cutoff-exclusion count equals the independently calculated expected count, and the reported
  pruning ratio matches its specified formula; the count of pairs retained because a valid
  measurement or configured error bound was unavailable also matches the independently calculated
  count.
- **SC-005**: Ledger reconciliation schedules every missing or invalidated retained non-self pair
  once, schedules no valid committed or terminal pair again unless invalidated, and creates no
  duplicate for existing recoverable work; self-pairs remain resolved without network work.
- **SC-006**: Builds report their measured candidate counts and pruning ratio without a required
  target ratio; correctness is determined by endpoint validity, route-cutoff coverage, and ledger
  reconciliation rather than an assumed sparsity percentage.
- **SC-007**: Every qualifying committed or published route fact has an actual solved network
  cost classified against the configured cutoff; no over-cutoff result is committed or published
  as qualifying, and resume restores the same candidate policy and resolved execution limits.

## Assumptions

- Feature 001 supplies the solvable-cell set, canonical H3 polygons, and deterministic
  representative points; Feature 002 does not redefine eligibility.
- Feature 003 supplies ledger states, compatibility checks, and recovery behavior. This feature
  defines the expected logical OD keys and the rule for creating new work from them.
- A build uses one finite, nonnegative network cutoff with explicit units and a declared travel
  mode and restrictions.
- For AOI-to-surrounding mode, a finite conservative reach can be established from the configured
  cutoff and network-cost semantics. A build that cannot establish one fails rather than
  speculatively limiting destinations.
- The configured AOI boundary-intersection policy is authoritative; the existing default is
  inclusive.
