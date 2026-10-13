# Feature Specification: Resumable OD Solving

**Feature Branch**: `[003-resumable-od-solving]`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "Create Builder Feature 003: Resumable OD Solving. Specify the durable,
restart-safe lifecycle for solving directed OD candidate pairs from Feature 002. Define deterministic
work identities, durable states and leases, stale-worker fencing, deterministic representatives,
isolated solve output, validated atomic commits, outcome classifications, compatibility on AOI
expansion, and durable reconciliation. Keep storage and implementation choices open and preserve
ownership boundaries of Features 002, 004, and 005. Require restart fault-injection coverage at every
lifecycle boundary, plus lease reclaim, stale-worker rejection, invalid-stage handling, and
compatible AOI-expansion reuse."

## Clarifications

### Session 2026-10-13

- Q: When an AOI expansion changes inferred batch or execution limits, should previously
  completed route outcomes still be reusable if the network, endpoints, cost rules, cutoff, and
  result meaning are unchanged? → A: Yes; compatibility uses result-affecting inputs, while
  batch/execution settings remain run provenance.
- Q: How should a route that cannot be solved be distinguished as “unlocated” or “unreachable”?
  → A: They may be recorded as distinct ledger classifications, but both are equivalent
  unroutable outcomes for downstream analysis and are excluded from the final output dataset.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resume Interrupted Route Work (Priority: P1)

As a builder operator, I need interrupted route work to resume from durable evidence so that a
long-running OD build does not lose completed results or solve the same directed pair twice.

**Why this priority**: A build is not trustworthy or practical at scale unless recovery preserves
the exact expected pair set and recognizes results that were already committed.

**Independent Test**: Run a small known candidate set, interrupt after each durable lifecycle
boundary, restart, and compare reconciled logical outcomes with an uninterrupted reference run.

**Acceptance Scenarios**:

1. **Given** a planned work item and its expected directed logical keys, **When** a worker claims
   it, **Then** the ledger records the lease and the work progresses only through legal states.
2. **Given** execution stops after any durable lifecycle boundary, **When** the same compatible
   build resumes, **Then** committed outcomes are reused and every unresolved expected key is
   either resumed or scheduled once.
3. **Given** a worker lease expires and another worker reclaims the item, **When** the original
   worker later submits output, **Then** its stale lease is rejected and cannot stage or commit it.
4. **Given** a staged output omits an expected key, duplicates a key, includes an unexpected key,
   or has an invalid outcome, **When** the coordinator validates it, **Then** no result is
   committed and the failure is recorded for retry or terminal handling.

### User Story 2 - Account for Every Solve Outcome (Priority: P1)

As a builder operator, I need each expected pair to have an explicit, durable solve disposition so
that successful routes, valid non-routes, cutoff exclusions, and failures cannot be confused.

**Why this priority**: Reconciliation must distinguish a route that was not found from work that
never completed, and must not present an estimated or failed solve as an actual network cost.

**Independent Test**: Feed a synthetic bounded batch through successful, unlocated, unreachable,
over-cutoff, and transient or persistent system-failure cases, then reconcile its exact logical-key
outcomes.

**Acceptance Scenarios**:

1. **Given** a valid solvable origin and destination, **When** a route is solved, **Then** the
   result uses Feature 001's deterministic representatives and records the actual network cost
   and its configured units.
2. **Given** a representative cannot be located, a route is unreachable, or an actual solved cost
   exceeds the cutoff, **When** the solve outcome is classified, **Then** the corresponding
   `unlocated`, `unreachable`, or `cutoff-excluded` disposition is durably recorded for that
   logical key and is not represented as a qualifying route cost.
3. **Given** a system failure interrupts a solve, **When** the bounded retry policy is applied,
   **Then** the failure remains retryable while attempts remain and becomes a recorded terminal
   failure when the retry limit is exhausted.

### User Story 3 - Expand Coverage Without Repeating Compatible Work (Priority: P1)

As a builder operator, I need an expanded AOI build to reuse compatible completed OD outcomes
while scheduling only missing or explicitly invalidated candidate keys.

**Why this priority**: Larger coverage should build on already verified route work without
silently reusing results produced from a different network, representative, or solve policy.

**Independent Test**: Reconcile a first AOI run and a larger second AOI run against a fixture with
overlapping and new directed keys, then verify reuse and scheduling by logical OD key.

**Acceptance Scenarios**:

1. **Given** an expanded AOI and prior committed results with a compatible dataset fingerprint,
   **When** Feature 002's expected keys are reconciled, **Then** prior keys are reused regardless
   of their earlier work-item or batch identity and only new keys are scheduled.
2. **Given** a prior key or work item was explicitly invalidated, **When** it remains expected,
   **Then** it is scheduled once for a new attempt while the old immutable evidence remains
   non-authoritative.
3. **Given** a changed result-affecting input such as the network, deterministic representative,
   travel/cost or cutoff semantics, result schema, or software compatibility input, **When** a
   build is reconciled, **Then** incompatible prior outcomes are not reused. A change only to
   candidate-selection policy, AOI coverage, batch boundaries, or resolved execution limits
   changes the expected universe or run provenance and MUST NOT by itself invalidate overlapping
   compatible outcomes.

### Edge Cases

- Reversed pairs `(A, B)` and `(B, A)` are distinct logical keys; a work-item ID is not a logical
  OD key and must not be used as a substitute for pair-level reconciliation.
- Candidate batching may change as AOI coverage grows. Committed outcomes remain reusable by
  logical key even if their prior work-item ID or destination batch no longer matches.
- An expired lease may be reclaimed repeatedly; each reclaim fences all earlier lease tokens.
- A worker may finish a solve after its lease expires; its result cannot become authoritative.
- A crash after an immutable part is written but before its ledger commit must not expose that
  uncommitted part as an active result or cause a duplicate active logical key on restart.
- Retrying an item must preserve its deterministic work-item ID while advancing attempt/fencing
  evidence; explicit invalidation may schedule a new generation of that item.
- Invalid deterministic representatives or endpoint references fail before network solving and
  are recorded, not silently omitted.
- A batch may contain both route outcomes and valid no-route/cutoff outcomes; every expected key
  still requires exactly one classified resolution.
- A zero-candidate plan reconciles successfully without leasing or invoking a network solve.
- A terminal system failure remains visible and is not automatically retried on later AOI
  expansion unless explicitly invalidated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat a logical OD key as the ordered pair
  `(origin_h3_id, destination_h3_id)`. Direction MUST be significant, and the key MUST be
  independent of dataset fingerprint, work item, batch, attempt, and output location.
- **FR-002**: The system MUST distinguish each logical OD key from its work-item ID. A work-item
  ID MUST be deterministic from the compatible dataset fingerprint, solvable origin, and
  canonical bounded destination batch assigned by Feature 002. Equivalent inputs MUST produce
  the same ID; changes to any of those identity inputs MUST produce a different ID. The ID format
  and storage representation remain implementation choices.
- **FR-003**: Each work item MUST durably record its fingerprint, origin, bounded destination
  batch, unique expected logical OD keys, lifecycle state, attempt and fencing evidence, and
  references to staged or committed results. Its expected keys MUST be retained non-self
  candidates from Feature 002; self-pairs and prefilter-pruned pairs MUST NOT be sent to the
  network solver.
- **FR-004**: The durable ledger MUST be authoritative for work ownership, state, expected
  logical keys, and active committed outcomes. Worker scratch data MUST NOT be the sole record
  that work was planned, solved, staged, or committed.
- **FR-005**: Work MUST use the states `planned`, `leased`, `solving`, `staged`, `validated`, and
  `committed`, as well as `retryable_failure`, `terminal_failure`, and `invalidated`. Legal
  transitions MUST be limited to:
  - `planned` to `leased`, `terminal_failure`, or `invalidated`;
  - `leased` to `solving`, `retryable_failure`, `terminal_failure`, or `invalidated`;
  - `solving` to `staged`, `retryable_failure`, `terminal_failure`, or `invalidated`;
  - `staged` to `validated`, `retryable_failure`, `terminal_failure`, or `invalidated`;
  - `validated` to `committed`, `retryable_failure`, `terminal_failure`, or `invalidated`;
  - `retryable_failure` to `planned`, `terminal_failure`, or `invalidated`;
  - `terminal_failure` or `committed` to `invalidated`; and
  - `invalidated` to `planned` only when the still-expected work is explicitly scheduled again.
  Repeated or out-of-order transitions MUST be rejected or be an idempotent no-op when they
  repeat the already recorded transition.
- **FR-006**: Leases MUST have an owner, a finite expiry, and a fencing value that changes on
  reclaim or invalidation. Only the current lease owner may advance leased work to solving or
  submit its result for staging. Lease expiry MUST make the previous token unusable before new
  work is accepted. A stale worker MUST NOT stage, validate, commit, or replace authoritative
  outcomes.
- **FR-007**: The coordinator MUST own validation and commit. A lease expiring in `leased` or
  `solving` MUST transition through `retryable_failure` and back to `planned` when attempts remain,
  or to `terminal_failure` when the bounded retry policy is exhausted. Reclaim MUST NOT treat
  worker status as proof of completion. A durably staged artifact MAY be revalidated after restart
  only when its fingerprint, accepted fencing evidence, expected keys, and result validity pass
  coordinator checks; otherwise the work returns to retry under the bounded policy.
- **FR-008**: Each solver MUST use only the deterministic, validated Feature 001 representative
  for each solvable endpoint in the compatible dataset. Solve output MUST be isolated from other
  workers and from authoritative committed output. A worker MUST NOT write directly to a shared
  final partition or ledger commit location.
- **FR-009**: The coordinator MUST stage each bounded work result before validation. Validation
  MUST compare the complete staged logical-key set with the item's expected logical-key set and
  require exactly one valid classified outcome per expected key, with no missing, duplicate, or
  unexpected keys. It MUST also reject invalid endpoint identity, incompatible fingerprints,
  non-finite or unit-incompatible costs, and qualifying costs that have not been checked against
  the configured actual-network cutoff.
- **FR-010**: Only validated staged output MAY be committed. The immutable result part and the
  ledger's authoritative committed reference MUST become visible atomically: recovery MUST observe
  either neither as committed or both as committed. Committed parts MUST NOT be edited in place.
  The authoritative committed set MUST contain at most one outcome per logical OD key. Repeating
  an identical commit MUST be idempotent; a conflicting duplicate MUST be rejected or explicitly
  supersede an invalidated result atomically.
- **FR-011**: The system MUST durably classify and reconcile each expected key as a solved
  qualifying route, `unlocated`, `unreachable`, or `cutoff-excluded`, or as an unresolved/system
  failure. `unlocated` and `unreachable` MAY be separately recorded for diagnostics, but MUST be
  treated as equivalent unroutable outcomes for downstream analysis and MUST NOT appear in the
  final output dataset. `cutoff-excluded` MUST be determined from actual network cost after solving
  and MUST NOT be exposed as a qualifying route cost or included in the final output dataset. A
  system failure MUST remain retryable until the configured bounded attempt policy is exhausted,
  then become a visible `terminal_failure`; failures MUST NOT be converted to success-shaped
  results or included as route facts.
- **FR-012**: Explicit invalidation MUST durably withdraw affected committed outcomes from the
  authoritative result set without modifying their immutable parts, fence in-flight workers, and
  allow still-expected keys to be scheduled again. Terminal failures MUST remain unscheduled until
  explicitly invalidated.
- **FR-013**: The compatible dataset fingerprint MUST include every input that can change the
  meaning or validity of a solved outcome: network identity/version, travel mode and restrictions,
  cost attributes and units, cutoff and outcome-classification policy, H3 resolution and endpoint
  eligibility/representative identity, result schema compatibility, and software compatibility
  versions. AOI geometry, derived candidate coverage, destination batch boundaries, resolved
  execution limits, and candidate-planning provenance MUST NOT alone make route outcomes
  incompatible. Those run-specific values MUST still be retained as provenance. A change to an
  included result-affecting input MUST prevent reuse unless compatibility is explicitly proven.
- **FR-014**: On initial planning and AOI expansion, the system MUST reconcile each expected
  logical OD key against compatible authoritative committed outcomes and existing work. It MUST
  reuse compatible committed outcomes by logical key, continue compatible recoverable work without
  creating a duplicate, leave terminal failures unscheduled unless invalidated, and schedule each
  missing or invalidated key exactly once. Batch changes MUST NOT invalidate an otherwise
  compatible committed logical key.
- **FR-015**: Reconciliation MUST derive completion from Feature 002's expected logical OD keys
  and durable per-key/work-item states, never from filenames, worker process status, or the
  presence of an unreferenced staged part. It MUST report unresolved, retryable, terminal-failure,
  and committed outcome counts separately. A solve plan is reconciled only when every expected
  key has exactly one compatible committed outcome or an explicit durable terminal-failure
  disposition; it MUST distinguish reconciled-with-failures from all-success completion.
- **FR-016**: The ledger MUST retain sufficient provenance to explain each transition, lease
  expiry/reclaim, retry, invalidation, validation rejection, classification, and commit, and
  summary counts MUST reconcile exactly to the expected keys and work items.
- **FR-017**: Storage engine, serialization, hashing algorithm, lease duration, retry limit,
  destination batch sizing policy, worker scheduling, and final publication format MUST remain
  implementation choices subject to these observable contracts. This feature MUST NOT redefine
  Feature 002 candidate selection/batching policy, Feature 004 publication, or Feature 005's
  parallel-worker capability and fallback policy.

### Key Entities

- **Logical OD key**: The direction-sensitive ordered origin and destination H3 identifiers for
  one candidate pair.
- **Compatible dataset fingerprint**: Versioned identity for result-affecting inputs that
  determine whether prior pair outcomes remain valid; AOI geometry, derived coverage, batch
  boundaries, and execution-limit provenance are excluded when they are the only changes.
- **Work item**: A durable, deterministic bounded batch for one solvable origin, with explicit
  expected logical keys and lifecycle state.
- **Lease**: Time-limited work ownership with a fencing value that prevents an expired or
  superseded worker from changing authoritative state.
- **Staged result**: Isolated solve output awaiting coordinator validation against the work item's
  complete expected logical-key set.
- **Committed result part**: Immutable, validated outcomes atomically referenced by the durable
  ledger as the authoritative resolution for their logical keys.
- **Solve outcome**: A qualifying actual network cost or an explicit unlocated, unreachable,
  cutoff-excluded, retryable system-failure, or terminal-failure disposition.
- **Reconciliation**: Comparison of expected logical OD keys with compatible committed outcomes
  and durable outstanding/failure states to determine solve completion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Fault-injection restart tests after every durable lifecycle boundary—planning,
  lease acquisition, solve start, staging, validation, immutable-part write, and commit
  acknowledgement—reconcile to the same expected logical outcomes as an uninterrupted reference
  run, with zero lost outcomes and zero duplicate authoritative logical keys.
- **SC-002**: Lease-expiry tests reclaim every expired leased/solving work item, and 100% of
  submissions using an expired or superseded fencing value are rejected before staging or commit.
- **SC-003**: 100% of staged-output tests containing a missing, duplicate, unexpected, or invalid
  logical-key outcome are rejected without changing the authoritative committed set.
- **SC-004**: AOI-expansion tests reuse 100% of compatible committed overlapping keys, schedule
  each new or explicitly invalidated expected key exactly once, and reuse zero outcomes with an
  incompatible fingerprint.
- **SC-005**: Reconciliation tests independently enumerate expected keys and verify that committed,
  retryable, terminal, and unresolved counts account for each key exactly once; a worker exit or
  stray filename alone never marks work complete.
- **SC-006**: Outcome tests classify all fixture cases as qualifying actual route, unlocated,
  unreachable, cutoff-excluded, retryable system failure, or terminal failure; no cutoff-excluded
  or failed case appears as a qualifying route cost.
- **SC-007**: Identical compatible inputs produce identical logical keys and work-item IDs,
  irrespective of candidate input order; reversing origin and destination changes the logical key.

## Assumptions

- Feature 001 supplies unique solvable cells with validated deterministic representatives and
  compatibility evidence; Feature 003 does not reselect representatives or redefine eligibility.
- Feature 002 supplies the expected directed candidate keys, self-pair and prefilter dispositions,
  deterministic origin grouping, bounded destination batches, candidate policy, and resolved
  execution limits. Feature 003 does not change candidate selection.
- A configured bounded retry policy exists; the precise attempt count and delay are implementation
  choices and are recorded durably.
- An AOI expansion changes the candidate universe but not the meaning of a pair outcome when all
  result-affecting network, endpoint, cost, cutoff, schema, and software inputs remain compatible.
  Run-specific candidate and execution settings remain recorded but do not alone prevent reuse.
- A durable terminal failure is reported distinctly from successful route resolution. Reconciled
  work may therefore be complete-with-failures without being represented as an all-success run.
- Feature 004 consumes validated solve outcomes and owns final dataset publication and its
  publication format. Feature 005 owns capability probing, parallel safety, and fallback behavior.
- Acceptance tests use synthetic network and ledger evidence; non-spatial ledger and reconciliation
  tests do not require geometry-processing dependencies.
