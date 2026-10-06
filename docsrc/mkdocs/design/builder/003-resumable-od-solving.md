# Feature 003: Resumable OD Solving

Use states `planned -> leased -> solving -> staged -> validated -> committed`, plus retryable, terminal, and invalidated failures.

- Derive work IDs from dataset fingerprint, solvable origin, and destination batch.
- Keep the ledger outside worker scratch geodatabases.
- Use expiring leases.
- Load only deterministic representatives for solvable cells.
- Stage, validate, and atomically commit immutable parts.
- Reconcile expected logical OD keys, not filenames.
- Reject or audit duplicate logical keys.
- Preserve compatible work when enlarging the AOI.
- Classify unlocated, unreachable, cutoff-excluded, and system failures.

Acceptance tests terminate execution at every lifecycle boundary and prove a restart neither loses nor duplicates committed results.
