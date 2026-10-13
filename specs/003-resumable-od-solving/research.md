# Research: Resumable OD Solving

## Decisions

### Use SQLite for the initial local ledger implementation

**Decision**: Keep the Feature 003 contract independent of a particular storage engine, while
using the Python standard-library SQLite implementation for the initial local ledger backend.

**Rationale**: The ledger needs durable transitions, unique active logical-key claims, and one
atomic transaction that publishes an immutable result-part reference with its key ownership.
SQLite supplies those guarantees in the supported Python environments without adding a runtime
dependency. The implementation choice does not constrain a future backend that satisfies the same
contract.

**Alternatives considered**:

- Leave the backend abstract in executable code. Rejected because the acceptance contract requires
  durable restart behavior and atomic key claims that need a concrete implementation to validate.
- Add a database dependency. Rejected because the local embedded ledger does not require a service
  and the standard library provides the required transaction primitive.

### Keep the ledger storage engine open

**Decision**: Specify behavior through a durable ledger contract without selecting a database,
file format, or storage service.

**Rationale**: The feature request explicitly keeps storage choices open. The requirements can be
tested at the contract boundary: durable state survives process restart, compare-and-transition
operations reject stale fencing values, and one atomic commit point controls authoritative result
visibility.

**Alternatives considered**:

- Select a particular database now. Rejected because no deployment or multi-host requirement is
  specified and it would prematurely constrain the feature.
- Treat worker output files as the ledger. Rejected because filenames and scratch artifacts cannot
  establish ownership, expected-key completeness, or authoritative commit.

### Separate result compatibility from run provenance

**Decision**: Reuse committed outcomes by logical OD key when a versioned result-compatibility
identity matches. Store AOI scope, candidate planning evidence, batch layout, and resolved
execution limits as run provenance rather than result-compatibility inputs.

**Rationale**: Clarification established that changes to inferred batch or execution limits during
AOI expansion must not alone trigger route re-solving. Route reuse still requires the same
result-affecting network, endpoint representative, cost, cutoff/classification, schema, and
software inputs. Expected logical keys gate reuse, so broader coverage only adds its newly expected
keys.

**Alternatives considered**:

- Fingerprint every run and planning value as a single compatibility identity. Rejected because an
  AOI expansion or sizing change would invalidate unchanged route facts.
- Reuse solely by logical key. Rejected because the same cells can yield different actual costs
  under changed networks, representatives, cost semantics, or cutoffs.

### Use fencing tokens and coordinator-owned commits

**Decision**: A lease carries an owner, expiry, and monotonically changing fencing value. Each
state transition and staged-output acceptance checks the current lease; only the coordinator
validates and makes a result authoritative.

**Rationale**: A worker can continue after lease expiry or after a coordinator restart. Checking
ownership at acceptance and commit prevents a late result from superseding work reclaimed by a
new owner.

**Alternatives considered**:

- Trust worker liveness or process status. Rejected because process status is not durable and can
  be unknown after interruption.
- Validate only when the lease is initially acquired. Rejected because the lease can expire during
  solving.

### Treat atomic ledger visibility as the result commit point

**Decision**: Write immutable result content into isolated staging, validate it, then atomically
record both the authoritative part reference and its unique logical-key ownership in the durable
ledger. Unreferenced staged content is not committed.

**Rationale**: This defines a single recovery-visible commit point while allowing the selected
backend to use a transaction or an equivalent atomic authoritative-record replacement.

**Alternatives considered**:

- Treat the existence or rename of a result file as commit. Rejected because a crash can leave
  orphaned parts and duplicate logical keys.
- Update part and ledger state in separate non-atomic operations. Rejected because a crash between
  them leaves ambiguous authority.

### Keep serial solving as the reference path

**Decision**: Validate lifecycle and route-result equivalence through a serial reference
coordinator first; isolate solve scratch regardless of execution mode and defer parallel
capability/fallback behavior to Feature 005.

**Rationale**: The constitution requires a correct serial path and assigns concurrency safety and
fallback to Feature 005.

**Alternatives considered**:

- Design a parallel scheduling policy as part of Feature 003. Rejected because Feature 005 owns
  capability probing, safe concurrency, and fallback.

## Project Evidence

- `src/h3_route_data_builder/od/models.py` already defines directed logical pair keys,
  candidate-plan records, ledger evidence, and bounded per-origin work-unit handoff.
- `src/h3_route_data_builder/od/candidates.py` already provides portable candidate
  reconciliation, deterministic batching, and actual-cost cutoff classification.
- `src/h3_route_data_builder/eligibility/run_state.py` provides an existing pattern for explicit
  legal lifecycle transitions and atomic durable state replacement.
- `src/h3_route_data_builder/eligibility/staging.py` provides an existing pattern for isolated
  staged parts, row-count/checksum verification, and atomic file replacement; Feature 003 must add
  expected-logical-key validation and ledger-authoritative commit semantics.
- Constitution Principles II, V, IX, XI, XIII-XV define the portable boundary, resumability,
  observability, serial reference, durable lifecycle, isolation, and atomic publication
  constraints.

## Unresolved Implementation Choices

None are specification blockers. Backend, encoding, lease duration, retry counts/delays, and
hashing format are explicitly implementation choices and MUST be selected and justified during
implementation without weakening the contracts.
