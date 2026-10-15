# Feature Specification: Parallel Execution

**Feature Branch**: `[005-parallel-execution]`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "Create Builder Feature 005: Parallel Execution. Read the shared
constitution and builder Features 001–004 before drafting. Specify how the builder can execute
work in parallel while preserving the serial implementation’s logical results and the durability
guarantees of Feature 003. Define a one-process reference implementation and the behavior that
serial and parallel execution must share; identify parallelizable work and coordinator ownership
of leases, reconciliation, and publication; use process isolation for ArcPy network solving;
require unique worker scratch and safeguards against writes to shared scratch or final partitions;
define bounded work, outcome reporting, cancellation, crashes, and lease-expiry handling through
Feature 003; require a small probe against the actual network and license configuration before
enabling parallel solves; define explicit fallback for capability or runtime failures; identify
safe non-ArcPy parallel tasks; keep tuning configurable only where needed without weakening
correctness or isolation. Do not redefine candidate selection, solve states, or publication."

## Clarifications

### Session 2026-10-13

- Q: When parallel execution is disabled after a runtime failure, should in-flight work be fenced and retried serially, or should workers be allowed to finish while only undispatched work switches to serial? → A: Fence or expire incomplete in-flight assignments and retry them serially; accept completed work only when current Feature 003 lease and fencing checks still permit it.
- Q: If a capability probe fails at the requested number of workers, should the builder try a smaller worker count before falling back to serial execution? → A: Try smaller counts in a bounded way and use the highest concurrency that passes; provide a `parallel_solving.enabled` configuration key to disable parallel solving and use serial execution. A null or absent value means parallel solving is enabled.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preserve a Serial Reference Run (Priority: P1)

As a builder operator, I need a correct one-process execution path that uses the same candidate,
solve, reconciliation, and publication contracts as parallel execution so that results remain
available when parallel execution is disabled or unsafe.

**Why this priority**: Serial execution is the correctness reference and the required recovery
path for systems where concurrent network solving cannot be certified.

**Independent Test**: Run a bounded fixture through the one-process path and verify its candidate
keys, per-key solve classifications and costs, durable ledger dispositions, and published logical
rows against independently calculated expectations.

**Acceptance Scenarios**:

1. **Given** a compatible bounded plan, **When** it runs in serial mode, **Then** the coordinator
   executes the same work units and applies the same validation, classification, reconciliation,
   and publication rules as parallel mode.
2. **Given** serial and parallel execution of the same fixture and result-affecting inputs,
   **When** their authoritative results are compared by logical OD key, **Then** the key sets,
   endpoint identities, outcome classifications, units, and canonical costs are equivalent.
3. **Given** an operator disables parallel solving or the capability probe does not authorize it,
   **When** the build starts, **Then** all eligible work can still proceed through the serial path
   without changing candidate or publication semantics.

### User Story 2 - Execute Network Solves in Isolated Processes (Priority: P1)

As a builder operator, I need independent bounded solve work to run in isolated processes so that
ArcPy and Network Analyst state, temporary datasets, and file geodatabases are not shared between
concurrent workers.

**Why this priority**: Process isolation avoids relying on thread-safety for ArcPy and prevents
workers from corrupting one another's intermediate or authoritative data.

**Independent Test**: Run multiple small work units with instrumented workers and assert that
each process receives a bounded coordinator-issued assignment, creates unique scratch locations,
returns outcomes only to the coordinator, and never writes to a shared scratch or final output
location.

**Acceptance Scenarios**:

1. **Given** parallel solving is authorized, **When** the coordinator dispatches work, **Then**
   each worker process receives only bounded work already assigned under a current Feature 003
   lease and its expected logical keys.
2. **Given** two workers execute simultaneously, **When** they create temporary solve output,
   **Then** each uses a unique scratch directory and geodatabase, and neither writes to another
   worker's scratch nor to a shared final partition.
3. **Given** a worker completes or fails, **When** it reports its bounded result, **Then** it
   returns outcome data and lease/fencing evidence to the coordinator; it cannot change ledger
   state, reconcile expected keys, or commit results.
4. **Given** the coordinator receives a result, **When** the Feature 003 lifecycle accepts or
   rejects it, **Then** only the current lease and fencing evidence can proceed through the
   authoritative staging, validation, and commit path.

### User Story 3 - Probe Capability and Fall Back Safely (Priority: P1)

As a builder operator, I need parallel solving enabled only after a small probe succeeds against
the configured network and licenses, with clear fallback when capability or runtime stability is
insufficient, so that concurrency failures do not appear as successful builds.

**Why this priority**: ArcPy, network locks, and Network Analyst licenses vary by runtime and
deployment; capability must be demonstrated rather than assumed.

**Independent Test**: Exercise successful and failing network/license probes and injected worker
initialization, lock, license, crash, and timeout failures. Verify parallel work is gated or halted,
the fallback is observable, and all unresolved work remains subject to Feature 003 reconciliation.

**Acceptance Scenarios**:

1. **Given** a request for parallel solving, **When** the preflight probe runs, **Then** it uses
   the configured network, actual license configuration, representative input, bounded isolated
   scratch, and a small solve to test worker initialization and concurrent capability without
   writing authoritative output. If the requested concurrency fails, it tests lower worker counts
   down to two and enables the highest count that passes.
2. **Given** all tested parallel worker counts fail because of unavailable licenses, unsafe
   network access or locking, ArcPy initialization failure, invalid probe results, or timeout,
   **When** the build proceeds,
   **Then** parallel solving is disabled, a reason is logged and reported, and eligible work is
   run serially when the serial path is available.
3. **Given** runtime lock, license, initialization, worker-crash, timeout, or repeated stability
   failure after parallel work begins, **When** the coordinator detects it, **Then** it stops new
   parallel dispatch, fences or allows leases to expire for incomplete in-flight assignments,
   retries them serially under Feature 003, records the fallback reason, and uses serial execution
   for eligible remaining work. Completed results proceed only if current lease and fencing checks
   still permit acceptance.
4. **Given** any worker failure or cancellation, **When** the run is reconciled, **Then** no
   failed, stale, unvalidated, or missing result is reported as successful; terminal failures and
   unresolved work remain visible under Feature 003 rules and block all-success completion and
   publication as specified by Features 003 and 004.

### User Story 4 - Parallelize Safe Non-Spatial Work (Priority: P2)

As a builder maintainer, I need independent non-ArcPy preparation and local validation work to be
parallelizable without moving ownership of candidate planning, durable reconciliation, or
publication, so that safe concurrency can be used beyond network solves.

**Why this priority**: Bounded independent data preparation and per-artifact checks can use
parallel execution without making ArcPy or shared durable state concurrent.

**Independent Test**: Run independent deterministic preparation and per-artifact validation jobs
serially and concurrently; verify equivalent outputs and diagnostics, bounded preparation
concurrency and buffering, and coordinator-owned aggregate checks and publication.

**Acceptance Scenarios**:

1. **Given** independent bounded non-spatial preparation jobs, **When** they run concurrently,
   **Then** their normalized inputs and outputs are equivalent to serial execution and do not
   mutate shared state.
2. **Given** immutable independent staged artifacts, **When** local checks such as checksum,
   schema, or row-count validation are parallelized, **Then** each artifact's result is returned
   to its owning coordinator and required cross-artifact reconciliation remains coordinator-owned.
3. **Given** any non-ArcPy parallel preparation or validation failure, **When** the owner
   collects results, **Then** it is reported explicitly and the owning Feature 002, 003, or 004
   contract determines whether the work may retry, must fail, or may proceed.
4. **Given** at least two eligible preparation units while network solving is serial, explicitly
   disabled, or has fallen back after a failed probe, **When** preparation runs, **Then** units are
   processed concurrently with at most two active units and at most two completed payloads waiting
   for lease or dispatch.

### Edge Cases

- A zero-work plan runs and reconciles without starting workers or requiring a concurrent-solve
  probe.
- A probe cannot find a safe representative pair or cannot obtain its configured Network Analyst
  capability; parallel solving is not authorized by inference or by worker startup alone.
- Requested parallelism exceeds available execution limits, worker resources, or demonstrated
  CPU-visible capacity; the configured worker ceiling is reduced to the available logical CPU
  count before probing. The probe then tests lower counts and uses the highest successful parallel
  count, or the run falls back to serial if no count of at least two succeeds.
- The operator disables parallel solving with `parallel_solving.enabled`; the run uses the serial
  path without running the parallel capability probe or starting concurrent ArcPy workers.
- `parallel_solving.enabled` is null or absent; the setting is treated as enabled and the
  capability probe governs whether parallel solving may proceed.
- Two assignments contain the same logical key because of stale or invalid planning; the
  coordinator rejects duplication rather than letting workers race to publish it.
- A worker returns after its lease expires or after cancellation; Feature 003 fencing rejects
  its result, including any late result from a process that did not stop promptly.
- A process crashes after writing scratch output but before reporting completion; scratch is
  non-authoritative and the ledger lease/retry lifecycle controls recovery.
- A worker cannot initialize ArcPy, open the network, acquire a required license, or safely
  complete a solve because of a lock; fallback is recorded and is not mistaken for a successful
  solve.
- Cancellation occurs while workers are solving; no new work is dispatched, active work is
  cancelled or allowed to stop within a bounded shutdown period, and unresolved keys remain
  visible to ledger reconciliation.
- A serial retry also fails; the failure is recorded under Feature 003 and is not hidden by the
  earlier fallback.
- A local file validation succeeds while aggregate logical-key reconciliation fails; publication
  remains blocked by Feature 004.
- Parallel preparation finishes in a different order from serial preparation; canonical ordering
  and logical content remain unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a correct one-process serial reference path before enabling
  parallel execution. Serial and parallel paths MUST use the same Feature 001 solvable-cell and
  representative inputs, Feature 002 expected logical keys and batches, Feature 003 solve
  classification and durable lifecycle, and Feature 004 publication validation and visibility
  rules.
- **FR-002**: For identical result-affecting inputs and expected logical keys, serial and parallel
  execution MUST produce logically equivalent results: identical directed key sets, endpoint
  identities, durable outcome classifications, units, and canonical cost values. Physical file
  ordering, run timestamps, worker assignment, and other execution provenance MAY differ.
- **FR-003**: The coordinator MUST accept the candidate plan from Feature 002 and own Feature 003
  lease acquisition and renewal, dispatch, result acceptance, cancellation, fallback decisions,
  durable reconciliation, and publication handoff. Workers MUST NOT acquire or renew leases,
  mutate ledger state, decide
  completion, reconcile the full expected-key set, or publish data.
- **FR-004**: Parallel network work MUST be assigned only as bounded Feature 003 work items or
  other explicitly bounded units whose logical keys are owned by the current coordinator lease.
  Work MUST NOT be duplicated or dispatched beyond configured and resource-resolved execution
  limits. The resource-resolved worker ceiling MUST be the lesser of the configured `max_workers`
  and the logical CPU count reported by `os.cpu_count()`, treating an unavailable CPU count as
  one. A worker assignment MUST include sufficient work identity and current fencing evidence for
  the coordinator to reject stale results.
- **FR-005**: ArcPy/Network Analyst solve workers MUST execute in separate operating-system
  processes. The system MUST NOT rely on multiple threads sharing ArcPy, Network Analyst solver
  objects, ArcPy environment state, or geodatabase scratch workspaces as its parallel-solve model.
  A worker MUST initialize its own ArcPy and solver state and receive serializable inputs rather
  than live ArcPy objects from the coordinator.
- **FR-006**: Each worker and active work assignment MUST use a unique scratch directory and
  geodatabase not used concurrently by another worker. Scratch identifiers MUST be collision-safe
  for simultaneous workers and retries. Workers MUST treat source network data as read-only and
  MUST NOT write directly to a shared ledger, shared scratch workspace, final dataset partition,
  publication reference, or completion marker.
- **FR-007**: Workers MUST return bounded outcomes tagged with work identity, attempt/fencing
  evidence, compatibility identity, and the logical keys represented. The coordinator MUST submit
  accepted results through Feature 003's existing staging, exact-key validation, classification,
  and atomic commit contract. Worker process status, scratch files, or reported success MUST NOT
  establish durable completion.
- **FR-008**: The coordinator MUST stop dispatching when cancellation is requested or a parallel
  failure disables parallel solving. It MUST request bounded graceful worker shutdown and may
  terminate unresponsive workers after the configured shutdown allowance. It MUST route every
  active or completed worker result through Feature 003 lease/fencing and retry rules; expired or
  stale results MUST be rejected. When runtime failure disables parallel solving, incomplete
  in-flight assignments MUST be fenced or allowed to expire and retried serially under Feature
  003; completed assignments MAY be accepted only when current lease and fencing checks permit.
  Scratch output from cancelled or failed work MUST remain non-authoritative and be cleaned only
  when its owning process is stopped and cleanup is safe.
- **FR-009**: Before parallel solving is enabled for a build, a bounded capability probe MUST
  exercise the configured network and actual Network Analyst license configuration using
  isolated scratch and representative inputs. The probe MUST verify the required worker
  initialization, network access, license acquisition, and successful bounded solve behavior at
  the requested concurrency. If that attempt fails, it MUST test lower concurrency levels,
  stopping at the highest successful level or after testing down to two workers. Probe output MUST
  be temporary and MUST NOT enter Feature 003's committed results or Feature 004 publication.
- **FR-010**: A failed, inconclusive, timed-out, or invalid capability probe MUST disable parallel
  network solving for that run only after no tested level of at least two workers passes, and
  select the serial reference path when it is available. If the CPU-resolved worker ceiling is
  below two, the system MUST skip the probe and select serial network solving with a structured
  reason. The result MUST include a structured reason for each failed attempt and the effective
  execution mode; the system MUST NOT silently claim parallel capability or all-success completion.
- **FR-011**: A runtime ArcPy initialization failure, unsafe network lock/contention, license
  acquisition failure, worker crash, or timeout MUST
  stop further parallel dispatch, explicitly record the cause and affected assignments, and
  fall back to serial execution for eligible work when possible. Incomplete in-flight assignments
  MUST be fenced or allowed to expire and retried serially. Completed in-flight or late results
  MUST be accepted only through current Feature 003 lease and fencing checks. Failure of serial
  recovery MUST remain a visible Feature 003 failure or unresolved disposition.
- **FR-012**: Execution reporting MUST distinguish requested mode, effective mode, capability
  probe result, fallback occurrence and reason, dispatched/completed/cancelled/failed work counts,
  and reconciled Feature 003 outcomes. Counts MUST reconcile to assignments and expected logical
  keys; fallback MUST NOT convert a failed or unresolved key into success.
- **FR-013**: Bounded independent non-ArcPy preparation MUST execute in parallel when at least two
  eligible units are available, provided it is deterministic, stateless or isolated, and produces
  the same canonical result as the serial operation. This preparation MUST normalize existing
  bounded Feature 003 work items and
  Feature 001 representative inputs into immutable, serializable solve-input payloads; it MUST NOT
  choose candidates, change pair keys or batch membership, or mutate ledger state. Whenever network
  solving is performed serially, including explicit serial mode, explicit parallel-solve
  disablement, probe fallback, and runtime fallback, eligible independent preparation MUST use
  bounded parallel execution as required by Constitution Principle XIV. Use standard-library
  concurrency of at most two active preparation units, independent of the ArcPy process worker
  ceiling and `parallel_solving.enabled`. Stream work items into preparation and bound prepared
  payloads waiting for lease/dispatch to at most two units; do not materialize the complete work
  plan or payload set. Preserve canonical ordering and explicitly report failures.
- **FR-014**: Checks that operate independently on immutable per-work-item or per-file artifacts,
  such as local integrity, schema, and row-count checks, MAY execute in parallel. Feature 003
  remains authoritative for work-result acceptance, expected-key reconciliation, and commit;
  Feature 004 remains authoritative for aggregate publication validation and atomic exposure.
- **FR-015**: Configuration MUST provide a `parallel_solving.enabled` setting that lets an
  operator disable parallel network solving; only an explicit false value disables it. A null or
  absent value MUST be treated as enabled. When disabled, the system MUST use the serial reference
  path without running the parallel capability probe or starting concurrent ArcPy workers; eligible
  non-ArcPy preparation MUST remain parallel as specified in FR-013. Configuration MAY otherwise
  select bounded concurrency and shutdown behavior, but MUST NOT disable process isolation, unique
  worker scratch, lease fencing, bounded work, capability probing, result validation, or observable
  fallback. Effective worker concurrency MUST be no greater than configured limits,
  resource-resolved limits, and the highest concurrency demonstrated by the probe.
- **FR-016**: Parallel-execution policy and relevant provenance MUST be recorded without changing
  Feature 003's result-compatibility fingerprint semantics. Execution mode, worker assignment,
  retries, and fallback MUST NOT by themselves alter logical OD key identity or make otherwise
  compatible committed results invalid.
- **FR-017**: Feature 005 MUST preserve the project boundary that ArcPy is imported only by the
  builder and is confined to network/geoprocessing operations. Non-spatial execution coordination
  and tests MUST remain importable and testable without ArcPy. GeoPandas MUST NOT be introduced
  as a dependency or used by this feature's implementation, tests, or tooling.

### Key Entities

- **Execution mode**: Requested and effective serial or parallel policy for a build, with
  observable fallback status.
- **Capability probe report**: Bounded evidence from the configured network and license
  environment indicating whether parallel solving is authorized and why.
- **Work assignment**: A coordinator-issued bounded Feature 003 work identity, lease/fencing
  evidence, compatibility identity, and expected logical keys.
- **Worker result**: A bounded set of classified outcomes and diagnostics associated with an
  assignment, not authoritative until accepted and committed by the coordinator.
- **Worker scratch workspace**: Unique process-owned temporary directory and geodatabase that
  cannot be shared with other workers or used as a final result location.
- **Execution summary**: Reconciled counts and provenance for requested/effective mode, probe,
  worker activity, cancellation, failures, fallback, and Feature 003 logical outcomes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every acceptance fixture, serial and parallel execution produce identical
  expected and authoritative logical-key sets and equivalent per-key outcome classifications,
  units, endpoint identities, and canonical cost values; zero duplicate or missing keys are
  accepted.
- **SC-002**: Across concurrent-worker tests, 100% of active workers have distinct scratch
  directories and geodatabases, and zero worker writes target a shared final partition or the
  durable ledger.
- **SC-003**: In every lifecycle test, only coordinator actions can lease, reconcile, validate,
  commit, or publish; stale, expired, cancelled, and unreferenced worker results produce zero
  authoritative commits.
- **SC-004**: Probe tests cover successful capability, step-down to a lower successful concurrency,
  and each configured failure category (license, initialization, network access/locking, invalid
  result, and timeout); when no concurrency of at least two passes, the run selects serial fallback
  when available and produces a non-empty observable reason.
- **SC-005**: Injected runtime worker crashes, timeouts, lock/license failures, and cancellation
  halt additional parallel dispatch; the execution summary accounts for every assignment and
  Feature 003 state, with no failed or unresolved key reported as all-success.
- **SC-006**: Parallel non-ArcPy preparation and per-artifact checks match serial canonical
  results for every fixture, while coordinator-owned full-key reconciliation and atomic
  publication continue to reject incomplete or inconsistent artifacts.
- **SC-007**: Zero-work plans start no solve workers and require no capability probe. Explicit
  serial mode, `parallel_solving.enabled: false`, or an ArcPy process ceiling below two starts no
  probe or concurrent ArcPy workers; eligible non-ArcPy preparation remains concurrent whenever
  it has at least two units. A failed probe occurs only after a probe was attempted, then selects
  serial network solving while preserving concurrent preparation. None of these modes changes
  Feature 002–004 behavior.
- **SC-008**: A null or absent `parallel_solving.enabled` setting is treated as enabled and proceeds
  through the capability probe when work exists and the CPU-resolved worker ceiling is at least
  two; only an explicit false value disables parallel network solving.
- **SC-009**: The resolved worker ceiling equals the lesser of configured `max_workers` and
  `os.cpu_count()`; if `os.cpu_count()` is unavailable, the ceiling is one. No dispatch or probe
  exceeds this resolved ceiling, and tests cover configured-below, configured-above, and
  unavailable-CPU cases.
- **SC-010**: For two or more eligible non-ArcPy preparation units, at least two are processed
  concurrently when execution permits, never more than two preparation units are active, and no
  more than two prepared payloads wait for lease/dispatch. Preparation remains concurrent when
  network solving is serial, explicitly disabled, or falls back after a failed probe.

## Assumptions

- Feature 001 remains authoritative for eligibility and deterministic network representatives;
  Feature 002 remains authoritative for candidate scope, prefiltering, expected keys, and
  deterministic bounded batches.
- Feature 003 remains authoritative for work-item identity, leases/fencing, state transitions,
  retries, result staging, validation, commits, and completion reconciliation.
- Feature 004 remains authoritative for the published schema, aggregate validation, immutable
  versions, and atomic publication.
- The serial reference path is the default when parallel solving is not explicitly requested or
  cannot be certified by the capability probe.
- A usable serial Network Analyst configuration is assumed for serial fallback. If even serial
  solving cannot initialize or acquire its required license, the run reports failure rather than
  success.
- Probe work uses known compatible representative inputs when available; if no safe bounded probe
  can be run, parallel solving is not certified and the system falls back to serial.
- Parallelism is an execution policy and provenance, not a change to result compatibility,
  candidate selection, durable state semantics, or publication meaning.
