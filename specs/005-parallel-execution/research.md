# Research: Parallel Execution

## Execution Boundary

- **Decision**: Keep one coordinator authoritative in both execution modes. Use the same bounded
  Feature 003 work items, lease/fencing validation, result staging, validation, and commit path.
  Serial execution invokes solve work in-process; parallel execution delegates only the bounded
  network solve to isolated child processes.
- **Rationale**: `od/solving.py` already provides the serial lifecycle, and `od/ledger.py` owns
  leases, fencing, staging, and commits. `network/solver.py` is the ArcPy boundary and already
  accepts isolated scratch. Reusing these contracts avoids giving workers durable-state authority
  or changing candidate and publication semantics.
- **Alternatives considered**: Letting child workers lease or commit would duplicate ledger
  ownership and permit stale workers to write authoritative state. A separate parallel-only
  acceptance path would risk serial/parallel behavior drift.

## Process Isolation

- **Decision**: Use operating-system processes with Python's explicit `spawn` context for
  ArcPy/Network Analyst work. Pass only picklable work, representative, network, and
  configuration data into an importable module-level worker; initialize ArcPy and solver state
  inside the child. Give each active assignment a unique scratch directory and geodatabase.
- **Rationale**: The project targets ArcGIS Pro on Windows, prohibits shared-thread ArcPy solver
  state, and the existing network solver requires unique scratch for each attempt. Process
  isolation also keeps ArcPy imports out of portable coordination and ledger modules. Python's
  multiprocessing documentation requires process targets and arguments to be importable and
  picklable under spawn; explicit spawn avoids relying on inherited ArcPy state. ArcGIS's
  `arcpy.nax` workflow initializes a solver against a network, sets options, loads inputs, solves,
  then consumes results, so each child must initialize and own its solver object
  ([Python multiprocessing](https://docs.python.org/3.13/library/multiprocessing.html#the-spawn-and-forkserver-start-methods);
  [ArcGIS Pro network analysis](https://pro.arcgis.com/en/pro-app/3.6/arcpy/network-analyst/performing-network-analysis.htm)).
- **Alternatives considered**: Shared-thread solving is excluded by the feature contract.
  Passing live ArcPy objects across processes is not portable or safe.

## Capability Probe and Fallback

- **Decision**: Run bounded probe solves using representative inputs from the current compatible
  work when parallel solving is enabled and work exists. Resolve the worker ceiling to
  `min(max_workers, os.cpu_count() or 1)`, then descend through smaller counts to two; select the
  highest successful count. If the resolved ceiling is below two or no level of at least two
  passes, use serial network solving while retaining parallel non-ArcPy preparation. Do not probe
  when the operator explicitly disables parallel network solving or there is no work; eligible
  non-ArcPy preparation remains parallel in serial-solve modes, bounded to two units concurrently.
- **Rationale**: The probe must exercise actual network access, licensing, child initialization,
  and solve behavior. A descending search is bounded by the configured and CPU-resolved ArcPy
  process ceiling and implements the clarification that partial capacity should be usable.
  ArcGIS tools fail when required product or extension licenses are unavailable, and license
  availability/check-out behavior depends on the ArcGIS Pro licensing model. Therefore worker
  startup or a parent-process license check alone cannot certify concurrent solves; each probe
  child must exercise the actual configured solve path. Temporary probe output is not ledger or
  publication data ([ArcGIS Pro license access in Python](https://pro.arcgis.com/en/pro-app/3.6/arcpy/geoprocessing_and_python/accessing-licenses-and-extensions-in-python.htm)).
- **Alternatives considered**: Treating the requested count as the only tested level would discard
  usable lower concurrency. Treating process startup alone as proof would not test the configured
  network or license.

## Runtime Failure Recovery

- **Decision**: On a runtime failure, stop dispatch, request bounded worker shutdown, and route
  completed output through the existing coordinator acceptance path. Fence or allow leases to
  expire for incomplete assignments, then retry eligible work serially under Feature 003.
- **Rationale**: The ledger remains the sole authority for whether a result is current and
  committed. Existing state transitions and retry limits already define recoverability.
- **Alternatives considered**: Accepting late results without current fencing evidence risks stale
  commits. Marking worker exit or scratch-file presence as success violates ledger reconciliation.

## Configuration and Dependencies

- **Decision**: Use the existing project configuration singleton and standard-library process
  facilities; add no package dependency. Treat `parallel_solving.enabled` as enabled when null or
  absent, and disable parallel solving only for an explicit false value. Bound concurrency by the
  configured ceiling, resource limits, and probe evidence.
- **Rationale**: Parallel policy belongs to Feature 005 and must not alter result compatibility.
  Python's standard library is sufficient for process isolation and avoids introducing a new
  runtime dependency into the ArcGIS Pro environment. The project already provides central YAML
  configuration loading and typed feature-specific config parsers.
- **Alternatives considered**: A new process-pool dependency would duplicate runtime functionality
  and add deployment burden. Putting parallel policy into candidate or publication configuration
  would cross feature ownership boundaries.

## Safe Non-ArcPy Work

- **Decision**: Permit only independent deterministic preparation and per-artifact checks to run
  concurrently. Preparation normalizes existing bounded Feature 003 work items and Feature 001
  representative inputs into immutable serializable payloads; it does not select candidates, alter
  keys or batches, or mutate the ledger. Keep candidate selection, expected-key reconciliation,
  lease mutations, aggregate validation, and publication coordinator-owned.
- **Rationale**: These ownership boundaries are already defined by Features 002–004. Local checks
  over immutable artifacts can be parallel without changing authoritative results.
- **Alternatives considered**: Concurrent mutation of candidate, ledger, or publication state is
  excluded because those operations require global ordering or atomic ownership.
