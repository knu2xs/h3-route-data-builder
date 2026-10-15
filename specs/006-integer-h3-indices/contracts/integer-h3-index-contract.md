# Integer H3 Index Contract

## Canonical Value and Names

This is the proposed incompatible shared contract `2.0.0`. It is not a claim that the external
solver already implements the new contract.

All H3 cell identities exchanged by the builder under this proposed shared contract are exact unsigned
64-bit integers. Use `h3_id` for a cell, and `origin_h3_id` and `destination_h3_id` for directed OD
endpoints. Field names do not encode a storage representation.

Consumers and builder boundaries reject hexadecimal or decimal strings, floating-point values,
booleans, negative and out-of-range values, and values that are not valid H3 cells at the
applicable resolution. A dependency-specific alternate representation, if required, is confined
to that library boundary and cannot become a builder-owned identity.

## Serialization Rules

- Arrow/Parquet H3 columns use `uint64`; in-memory references use exact integer values.
- JSON H3 fields and array elements are integer number tokens, never quoted identifiers.
- Cell-indexed maps serialize as sorted arrays of records with integer H3 fields, not as JSON
  objects keyed by H3. Directed keys serialize as ordered two-integer arrays.
- Manifest `origin_ids` and similar index collections are numeric arrays, including after
  partition compaction. Consumers must preserve integers above `2^53` without rounding.
- Decimal directory labels are non-authoritative filesystem syntax. Read typed columns and
  manifest values, not inferred Hive partition strings, for endpoint identities.
- Text-only dependency labels are transient adapter data; they must resolve to validated integer
  cells before returning results to builder logic.

## Directed Logical Key

The OD key is the ordered integer pair `(origin_h3_id, destination_h3_id)`. Direction matters;
reversing endpoints creates a different key. Fingerprints, work IDs, batches, and output locations
remain separate from logical-key identity.

## New Dataset Fields

- `solvable_cells.h3_id`: required unsigned 64-bit integer.
- `od_facts.origin_h3_id`: required unsigned 64-bit integer.
- `od_facts.destination_h3_id`: required unsigned 64-bit integer.
- No hex-string aliases or duplicate H3 identifier fields.
- Dataset/cell/fact schema versions are `2.0.0`; GeoParquet remains `1.1.0`.

Historical datasets retain the old field names, types, and schema identity and remain immutable.

## Durable State

New ledger endpoint and expected-key values use exact integer identities and a representation-aware
compatibility identity. A legacy hexadecimal-keyed ledger is rejected for resume. Rebuild requires
a separate working ledger; legacy results are not reused and the old ledger is not silently
deleted or overwritten.

SQLite physically stores validated cell indices in signed `INTEGER` columns. Valid H3 cells fit
that range, so this does not change the unsigned public identity or cause signed reinterpretation.
Ledger-format and canonical work-ID encodings use version `2`. Eligibility schema/fingerprint
version `2` prevents adoption of hexadecimal-keyed staged eligibility records.

## Coordinated Consumer Adoption

Builder and solver projects must agree on field names, unsigned type, H3 validity and resolution
rules, ordered key semantics, and contract version. Integer-keyed publications are not declared
compatible with the existing solver contract until the solver consumer and shared-fixture contract
tests have been updated.

The release evidence consists of the agreed contract version and matching fixture tests in both
projects. Builder-only tests may complete before that external adoption; they must not be reported
as completed cross-project integration.
