# Quickstart: Integer H3 Index Standardization

This guide defines acceptance validation for integer-indexed builder state and published datasets.
It does not require a mobile application or a performance benchmark.

## Portable Validation

These are post-implementation acceptance commands, not evidence that Feature 006 is implemented.
Use the configured project Python environment with H3 v4, PyArrow, DuckDB, and pytest installed.
Run from the repository root; use temporary test outputs only. ArcPy-dependent geometry/network
checks require ArcGIS Pro and Network Analyst and must report missing prerequisites separately.

From the repository root, run focused identity, eligibility, candidate, ledger, and publication
tests:

```powershell
python -m pytest `
    testing\test_eligibility_cells.py `
    testing\test_eligibility_rules.py testing\test_eligibility_output.py `
    testing\test_eligibility_fingerprint.py testing\test_eligibility_run_state.py `
    testing\test_eligibility_staging.py testing\test_od_candidates.py `
    testing\test_od_candidate_ledger.py testing\test_od_ledger.py testing\test_od_solver.py `
    testing\test_od_execution.py testing\test_od_execution_config.py `
    testing\test_od_execution_preparation.py testing\test_od_execution_workers.py `
    testing\test_od_execution_probe.py testing\test_publication_schema.py `
    testing\test_publication_conversion.py testing\test_publication_pruning.py `
    testing\test_publication_compaction.py testing\test_publication_manifest.py `
    testing\test_publication_validation.py testing\test_publication_interoperability.py `
    testing\test_publication_publish.py
```

For the US1 portable payload checkpoint, run the tests authored in T008 separately from
ledger-backed execution tests, which remain US2 acceptance:

```powershell
python -m pytest `
    testing\test_od_execution_preparation.py testing\test_od_execution_workers.py `
    -k "integer_payload"
```

Canonicalization validates type, range, and cell validity without a new resolution parameter.
Eligibility and candidate callers reject cells whose resolution differs from their configured
resolution before using or scheduling them; covering validates its existing resolution argument.

Expected results:

- Valid integer H3 values pass resolution-aware validation; strings, booleans, floats, negative,
  out-of-range, and invalid-cell values fail before use.
- Canonical ordering, deduplication, candidate membership, and directed OD keys are invariant
  under input permutation.
- Indices round-trip exactly through every new durable and Arrow/Parquet boundary.
- Valid cells at resolutions 0–15 and cells above `2^53` remain exact. SQLite endpoint columns
  return `typeof='integer'`; JSON index collections remain numeric arrays after reload.
- Result loading rejects string endpoints rather than using `str()` or parsing them as legacy
  aliases. Fingerprints and new-format work IDs are stable under input permutation.
- New schemas declare only unsigned integer H3 fields and a new schema identity.
- A hexadecimal-keyed ledger is rejected before resume. A fresh-ledger rebuild does not count its
  prior results as reused and does not overwrite or silently delete the legacy ledger.
- Legacy eligibility stages/completed runs are not adopted under the new schema fingerprint.
- Historical publication artifacts remain unchanged and identifiable by their existing version.
- New-format restart tests interrupt lease, solve, stage, validation, and commit boundaries;
  reclamation and stale-worker fencing neither lose nor duplicate integer logical keys.

## Shared Contract Validation

Before integer-keyed data is declared consumable by `h3-route-solver`, verify both projects use the
same field names, unsigned integer type, validity rules, ordered-key semantics, and contract
version. Run contract tests in both repositories against the same fixture.

The fixture must include cells above `2^53`, required uint64 fields, directed reverse pairs,
zero-cost self-pairs, unchanged geometry and route outcomes, and integer partition-manifest
origin arrays. Verify Arrow and DuckDB preserve the exact values. Record consumer approval and
fixture results; a passing builder-only run is not solver compatibility evidence.

## Geometry and Network Boundaries

```powershell
python -m pytest `
    testing\test_eligibility_geometry.py testing\test_network_eligibility.py `
    testing\test_od_candidate_geometry.py testing\test_real_network_dataset.py
```

Expected results: polygon/centroid/representative values and candidate membership do not change.
Network Analyst text labels map back to integer keys for both location status and route output.
Unknown labels fail explicitly. Real-network or license prerequisites that are missing/skipped
do not count as successful integration evidence.

## Regression Validation

Run the full builder test suite:

```powershell
python -m pytest
```

Expected results: candidate selection, route costs and classifications, serial/parallel parity,
and publication completion are unchanged except for index representation and required versioning.

For record scope, see [data-model.md](data-model.md). For cross-boundary rules, see
[contracts/integer-h3-index-contract.md](contracts/integer-h3-index-contract.md).

## Implementation Evidence (2026-10-15)

The configured interpreter is `env\python.exe` (Python 3.13.13, H3 4.5.0). No dependency
or backend change was needed. SQLite remains the working ledger; new endpoint storage is
integer-checked `INTEGER`, and Arrow/Parquet H3 columns are non-null `uint64`.

### Recorded Validation

- Before implementation: candidate, solver, and configured real-network baseline selection:
  **42 passed in 254.42 seconds**.
- Integer canonicalization tests were first observed failing, then passed: **25 passed**.
- Portable US1 checkpoint, including a real spawned-worker serialization round-trip:
  **99 passed**.
- Geometry/candidate-geometry and configured-network solver selection: **24 passed**.
- Network eligibility and configured real-network integration selection: **16 passed in
  268.50 seconds**. Source network data was only read; all writes used temporary fixtures.
- Regression excluding the separate real-network test module: **329 passed in 51.33 seconds**.
- Final additional acceptance selection for all-resolution eligibility staging, persisted
  AOI expansion/rebuild, and publication readers/validation: **81 passed in 8.71 seconds**.
  This includes tests added after the preceding regression selection.
- Feature-relevant Black checks at line length 100 pass (**66 files unchanged**), as does
  Python compilation. A repository-wide Black probe also identified 11 pre-existing
  formatting violations outside this feature's edits; those files were left alone.
  No static type checker is
  configured in the dependency manifests, and editor diagnostics are not exposed by the
  available tools. T042 remains unchecked for that unavailable diagnostic step; compilation
  and runtime tests are not represented as static type-checking evidence.
- Full suite: **331 passed, 1 failed in 523.02 seconds**. The only failure is the previously
  recorded full-suite logging-capture assertion in
  `test_streetmap_network_builds_reconciled_small_aoi_without_source_edits`:
  `"Execution limit batch_size="` was absent from `caplog.text`. The real build, reconciliation,
  version-2 manifest, uint64 schema and exact integer assertions preceding it passed.
  The isolated network selection above passed, including restart behavior. This existing
  logging-order failure is not represented as a green full-suite result.
- The 16 new all-resolution staging cases and the combined legacy-refusal/fresh-rebuild
  assertion were added after full-suite collection and passed in the final 81-test selection.
  These are separate results, not a second complete-suite run.

### Acceptance Coverage

| Requirements | Evidence |
|---|---|
| FR-001, FR-002, FR-005; SC-003 | Canonicalization, model/resolution rejection, candidate permutation/deduplication and directed reverse/self-pair tests. |
| FR-003, FR-004 | Canonical model/column names, typed manifest origins, exact JSON key arrays, and alias rejection. Opaque work/source IDs remain strings. |
| FR-006 | Opaque Network Analyst label round-trips; unknown, missing and duplicate label rejection; integer representative maps and spawned payloads. |
| FR-007; SC-001, SC-002 | SQLite storage-type assertions and exact ledger reload; uint64 eligibility stage and Arrow/DuckDB publication round-trips at resolutions 0-15, including greatest valid samples and values above `2^53`. |
| FR-008 | Proposed shared contract documented as `2.0.0`; external consumer agreement and matching solver fixture execution remain blocked under T038. |
| FR-009 | Eligibility schema/fingerprint 2, ledger format 2, work-ID encoding 2, fixed integer compatibility encoding, dataset/cell/fact 2.0.0 and schema-identity rejection tests. GeoParquet stays 1.1.0. |
| FR-010; SC-004 | Legacy/missing/inconsistent ledgers refused without changing bytes or directory contents, including WAL cases. Fresh-ledger expansion starts without legacy reuse, then reuses only compatible completed pairs. |
| FR-011; SC-005 | Historical schema identities are refused without relabeling or rewriting; publication membership/uniqueness, pruning, compaction and atomic visibility tests pass. |
| FR-012 | Existing representative, geometry, candidate/pruning, cutoff/outcome, batching, serial/parallel/fallback and lifecycle assertions remain in the converted tests. |

Restart tests recover and commit after every plan/lease/solve/stage/validate/commit interruption,
asserting one exact logical outcome and idempotent commit. Lease reclaim, stale fencing,
invalid staged output, failed commits, AOI expansion and invalidation remain covered.

### Operational Notes and Remaining Gates

- Preflight inspects an isolated temporary read-only snapshot, including any durable WAL,
  because opening a WAL database with SQLite `mode=ro` can still create source sidecars.
  Legacy originals and sidecars are not opened by SQLite during that check. Temporary
  snapshot space is required; concurrent changes during copying cause an explicit refusal.
- Choose a separate fresh working ledger/output location for the pre-alpha cutover.
  No legacy migration, silent deletion, or historical publication rewrite is performed.
- **T038 is blocked**: no solver maintainer approval or solver-side fixture result has been
  supplied. Builder-only reader tests are not cross-project compatibility evidence.
- Toolbox parameters, defaults and help semantics are unchanged, so no toolbox or XML help
  sidecar edit was necessary.
- Integer/edge-device efficiency is motivation only; no benchmark or mobile-support claim is made.
