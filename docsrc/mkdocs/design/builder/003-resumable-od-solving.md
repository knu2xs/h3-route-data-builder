# Feature 003: Resumable OD Solving

Feature 006 uses exact integer endpoints, version-2 work-ID and compatibility encodings,
and ledger format 2. SQLite `INTEGER` stores valid H3 cells exactly (their high bit is clear);
endpoint columns also enforce integer storage types. Existing legacy or inconsistent ledgers
are rejected read-only before initialization. Select a separate fresh ledger and rebuild;
there is no migration, automatic deletion, or reuse of abandoned hexadecimal work.

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
