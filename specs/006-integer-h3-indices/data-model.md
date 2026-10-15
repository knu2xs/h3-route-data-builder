# Data Model: Integer H3 Index Standardization

This feature changes H3 index representation and the compatibility identities that depend on it.
Feature 001 eligibility, Feature 002 candidate membership, Feature 003 lifecycle, Feature 004
publication lifecycle, and Feature 005 execution behavior remain authoritative.

## Canonical H3 Index

| Attribute | Meaning | Validation |
|---|---|---|
| `h3_id` | One H3 cell identity | Exact unsigned 64-bit integer; valid H3 cell at applicable resolution |
| `resolution` | H3 cell resolution | Existing configured range; matches the H3 index |
| `origin_h3_id` | Directed OD origin | Canonical integer referencing an eligible solvable cell |
| `destination_h3_id` | Directed OD destination | Canonical integer referencing an eligible solvable cell |

Builder-owned ordering, deduplication, key comparison, and deterministic serialization use the
numeric integer value. Hexadecimal strings are not canonical aliases. Boolean values are not
accepted as integer indices.

Implementation uses Python `int` and the existing H3 `basic_int` API. Values must satisfy integer
type, range, cell validity, and any supplied resolution constraint; `0` and `2^64 - 1` are not
valid cell endpoints. The uint64 range is the storage domain, not the accepted set of cells.

## Directed OD Key

| Attribute | Meaning | Validation |
|---|---|---|
| `logical_od_key` | `(origin_h3_id, destination_h3_id)` | Ordered integer pair; direction is significant |
| `work_id` | Feature 003 work identity | Opaque deterministic ID under existing semantics |
| `compatibility_fingerprint` | Result-affecting identity including representation/schema | Versioned; hex and integer work are incompatible |

H3 representation does not change candidate membership, directed-key ordering, destination
batching policy, or solve outcomes.

Work-ID canonical payload version becomes `2`; it hashes the compatible fingerprint, integer
origin, and numerically ordered integer destination batch. New equivalent input permutations
yield the same work ID. IDs need not match prior hex encodings, and retries of new work preserve
the new ID. Result compatibility and eligibility fingerprints include their new schema versions.

## Eligibility and Published Records

The new solvable-cell schema has one required unsigned 64-bit `h3_id` field. New OD facts use
required unsigned 64-bit `origin_h3_id` and `destination_h3_id` fields. New schemas contain no
hexadecimal H3 fields and no duplicate alternate H3 representations. Existing referential,
uniqueness, and reconciliation rules remain in effect.

New schema/contract versions distinguish integer-indexed datasets. Existing published artifacts
retain their original schema, values, and version and are not rewritten.

Proposed dataset, cell-table, and fact-table schema versions are `2.0.0`; the eligibility staged
schema is `2`. GeoParquet metadata, non-index fields, CRS, and nullability remain unchanged.
Partition origin lists and compaction metadata use integer arrays. Partition directory names
may render decimal values but never define logical identity.

## Working Ledger

The new ledger format stores H3 indices as exact integer values and includes a representation
version in its compatibility identity. A legacy hexadecimal-keyed ledger is incompatible and is
not migrated or resumed. A rebuild uses a separate explicitly selected ledger, does not count
legacy results as reused, and leaves the old ledger file intact.

Indexed origin/destination columns use SQLite `INTEGER NOT NULL`, with storage-type checks.
Only validated H3 cells are persisted. Their high bit is zero, so SQLite's signed 64-bit
physical type stores every valid cell exactly; no unsigned reinterpretation is needed.
Destination batches and expected/outcome keys remain JSON payloads with integer values, not text
indices. The ledger format marker is `2` and is checked before mutating an existing database.
All Feature 003 states, transitions, attempts, leases, and fencing remain unchanged.

## Serialized References and Worker Payloads

- In-memory cell/representative/geometry maps have integer keys.
- Persisted cell-indexed maps are arrays of records with integer H3 fields; JSON object keys must
  not carry H3 identity.
- Expected OD keys are two-integer arrays; batches and manifest origin lists are integer arrays.
- Worker payloads preserve those integer identities through spawn serialization.
- Network Analyst labels are opaque temporary tokens mapped to integer cells inside the adapter;
  unknown or duplicate labels fail validation rather than being coerced to keys.
- Consumers parse JSON integer values exactly; double-precision-only parsing is not conformant.
- New eligibility fingerprints and metadata prevent adoption of legacy string-keyed stages,
  even for otherwise identical source inputs.
