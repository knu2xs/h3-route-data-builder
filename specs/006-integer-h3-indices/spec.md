# Feature Specification: Integer H3 Index Standardization

**Feature Branch**: `006-integer-h3-indices`

**Created**: 2026-10-13

**Status**: Draft

**Input**: User description: "Standardize all H3 indices to use integers, not hexadecimal."

## Clarifications

### Session 2026-10-13

- Q: Should the specification require lossless migration of resumable legacy ledgers or allow
  rebuilding them? → A: Lossy reset/rebuild is acceptable; legacy work need not be preserved.

## User Scenarios & Testing

### User Story 1 - Use One Exact H3 Index Representation (Priority: P1)

As a builder maintainer, I need every H3 index owned by the builder to have one exact integer
representation so that cell identity, ordering, and directed OD keys cannot vary with hexadecimal
formatting, and so index handling is more efficient when datasets are stored or consumed on
resource-constrained edge devices such as phones.

**Why this priority**: H3 indices are the shared identity for eligibility, candidate planning,
resumable solving, and publication. Inconsistent representations can cause mismatched keys,
duplicate work, and incompatible data. Integer-valued indices also avoid carrying textual
hexadecimal identifiers through builder-owned processing and data exchange, supporting efficient
storage, comparison, and transfer for constrained consumers such as phones.

**Independent Test**: Process equivalent H3 indices through eligibility, candidate planning, and
OD key handling. Verify that each is represented and compared as the same unsigned integer and
that invalid or string-form indices are rejected at builder-owned boundaries.

**Acceptance Scenarios**:

1. **Given** a valid H3 index, **When** it is carried between builder-owned components, **Then**
   its value remains an exact unsigned 64-bit integer and is not represented as a hexadecimal
   string.
2. **Given** an H3 index represented by a hexadecimal string, decimal string, float, negative
   value, or value outside the unsigned 64-bit range, **When** it enters a builder-owned
   interface, **Then** it is rejected before it is used as a cell identity or scheduled for work.
3. **Given** the same valid cell set in different input orders, **When** the builder canonicalizes
   it, **Then** deduplication and numeric ordering are deterministic and candidate membership and
   directed-pair semantics remain unchanged.

### User Story 2 - Exchange and Resume Integer-Keyed Data (Priority: P1)

As a builder or solver consumer, I need newly produced durable and published data to identify H3
cells with integer-valued fields so that the shared contract has one unambiguous representation.

**Why this priority**: A canonical in-memory value alone is insufficient if ledgers and published
tables continue to use hexadecimal strings or dual representations.

**Independent Test**: Build and publish a fixture, inspect its declared schemas and values, and
verify that all H3 index fields and OD keys use exact unsigned integers with no hexadecimal ID
fields.

**Acceptance Scenarios**:

1. **Given** a newly initialized working ledger, **When** it records cells or OD keys, **Then**
   H3 indices are stored as integers and ordered by unsigned numeric value.
2. **Given** a newly published dataset, **When** a consumer reads the solvable-cell and OD-fact
   tables, **Then** the cell identifier and both directed endpoint fields are unsigned integer
   fields, with no hexadecimal-string or duplicate alternate H3-index fields.
3. **Given** an existing hexadecimal-keyed working ledger, **When** a run attempts to resume it,
   **Then** it is identified as incompatible and is not silently treated as resumable integer-keyed
   work.
4. **Given** an already published hexadecimal-keyed dataset, **When** this standard is adopted,
   **Then** its immutable contents are not rewritten or relabeled as integer-keyed; its existing
   schema version remains identifiable as historical.

### Edge Cases

- An integer that fits in the unsigned 64-bit range but is not a valid H3 index at the configured
  resolution is rejected before it becomes an endpoint.
- The greatest valid H3 index supported by the configured resolution retains its exact value
  through serialization, deserialization, comparison, and fingerprinting; it is never rounded or
  reinterpreted as signed. An unsigned 64-bit value that is not a valid H3 index is rejected.
- A third-party H3 operation that requires another representation is isolated behind a conversion
  boundary; the converted representation does not enter builder-owned state, keys, contracts,
  durable records, or published fields.
- A legacy working ledger may contain partially committed work. Reinitializing it for this
  standard may abandon that work; the run must not report it as reused or complete.
- Legacy immutable publications may coexist with new-schema publications, but schema versions
  must prevent them from being confused.

## Requirements

### Functional Requirements

- **FR-001**: The canonical value for an H3 index in builder-owned state and contracts MUST be an
  exact unsigned 64-bit integer in the range `0` through `2^64 - 1`.
- **FR-002**: Builder-owned interfaces that accept H3 indices MUST accept integer values only.
  They MUST reject hexadecimal strings, decimal strings, floats, booleans, negative integers,
  values outside the unsigned 64-bit range, and values that are not valid H3 indices at the
  applicable resolution before using them as identities or scheduling work.
- **FR-003**: Eligibility records, candidate and OD keys, work-ledger endpoints, reconciliation
  records, logs that include H3 indices, manifests that include H3 indices, and other
  builder-owned records MUST use the canonical integer value. They MUST NOT define or emit
  hexadecimal-string H3-index fields or retain duplicate string and integer H3-index fields.
- **FR-004**: Canonical H3 index fields MUST use the names `h3_id` for a single cell and
  `origin_h3_id` and `destination_h3_id` for directed OD endpoints. The names MUST NOT encode a
  representation such as `_hex` or `_uint64`.
- **FR-005**: Deduplication, ordering, and deterministic serialization of H3 indices MUST use
  unsigned numeric value. Directed OD identity MUST remain the ordered pair of integer endpoint
  values; reversing endpoints MUST continue to produce a distinct key.
- **FR-006**: When an external library boundary requires a representation other than the canonical
  integer, any conversion MUST be confined to that boundary. Values crossing back into
  builder-owned logic MUST be converted to and validated as canonical integers immediately.
- **FR-007**: Newly staged or published Arrow/Parquet schemas containing H3 indices MUST declare
  the index fields as unsigned 64-bit integers. Other durable working storage MAY use an exact
  integer physical type capable of representing every valid H3 cell, provided validation preserves
  the logical unsigned domain without rounding, signed reinterpretation, or textual identity.
  All new schemas MUST remove hexadecimal-string and alternate duplicate index fields and
  identify the incompatible schema change with a new schema or contract version.
- **FR-008**: The shared builder-solver data contract MUST be updated in coordination with the
  solver project before integer-keyed publications are treated as consumable under the shared
  contract. This feature MUST NOT unilaterally claim compatibility with the existing
  hexadecimal-keyed contract.
- **FR-009**: The canonical integer representation and its schema/contract version MUST
  participate in compatibility identity wherever that identity controls reuse, resume, or
  publication. Integer-keyed results MUST NOT be mixed with hexadecimal-keyed state under one
  compatibility identity.
- **FR-010**: A hexadecimal-keyed working ledger MUST be treated as incompatible with this
  standard. The operator MUST initialize a new working ledger and rebuild its work from compatible
  source inputs; preservation or lossless migration of legacy work is not required. The system
  MUST NOT claim legacy work as reused. The reset or rebuild MUST be observable and MUST NOT
  silently delete or overwrite the legacy ledger.
- **FR-011**: Existing published datasets MUST remain immutable historical artifacts. They MUST
  retain their original schema identity and MUST NOT be relabeled as conforming to the integer
  standard. New publications MUST use the integer schema.
- **FR-012**: Standardizing representation MUST NOT change H3 cell membership, eligibility,
  representative selection, candidate scope or pruning, directed-pair semantics, route costs,
  outcome classifications, work batching policy, or publication lifecycle except where a
  representation or compatibility version change is expressly required above.

### Key Entities

- **H3 index**: A valid cell identity represented as one unsigned 64-bit integer at its applicable
  resolution.
- **Directed OD key**: An ordered pair of integer H3 indices identifying an origin and destination;
  direction is significant.
- **Schema/contract version**: The declared identity of a data contract that distinguishes new
  integer-indexed records from historical hexadecimal-indexed records.
- **Working ledger**: Resumable solve state keyed by H3 indices and compatibility identity; legacy
  hexadecimal-keyed ledgers are not migrated by this feature.
- **Published dataset**: An immutable artifact whose schema version defines how H3 indices are
  represented to consumers.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of H3-index fields in newly created builder-owned records, ledgers, and
  publications are exact unsigned integer values; none are hexadecimal strings or duplicate
  alternate H3-index fields.
- **SC-002**: Every valid H3 index at each supported resolution, including the greatest valid
  index exercised by conformance tests, round-trips through each new durable and published
  boundary without precision loss, signed reinterpretation, or value change.
- **SC-003**: Reordering or duplicating valid integer inputs does not change canonical cell order,
  candidate membership, or the set of directed OD keys.
- **SC-004**: Every legacy hexadecimal-keyed working ledger is detected as incompatible before
  resume; a fresh rebuild produces a complete integer-keyed ledger without counting legacy work as
  reused.
- **SC-005**: Integer-keyed publications pass schema, endpoint-key uniqueness, and endpoint
  membership validation; historical hexadecimal-keyed publications remain unchanged and
  distinguishable by schema version.

## Assumptions

- H3 indices have an unsigned 64-bit canonical domain; resolution and H3 validity remain governed
  by existing configuration and validation.
- “All H3 indices” means all builder-owned values, keys, durable records, schemas, manifests, and
  shared-contract fields. It does not include non-H3 identifiers such as work-item IDs, source
  object IDs, or H3 resolution values.
- The published dataset schema change is intentionally incompatible and requires a coordinated
  update to the shared builder-solver contract and solver consumer.
- Efficiency, including storage and transfer to edge devices such as phones, is a primary
  motivation for using integer-valued indices. Performance targets and measurement methodology
  are outside this narrowly scoped representation specification.
- This is pre-alpha work. Legacy working ledgers may be abandoned and rebuilt from compatible
  source inputs; no lossless migration is required. Existing immutable published datasets remain
  historical artifacts and are not rewritten.
- Candidate selection, OD solving semantics, publication lifecycle, and non-index data fields
  remain governed by their existing features.
