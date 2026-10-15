# Research: Integer H3 Index Standardization

## Canonical Value and H3 Library Boundaries

- **Decision**: Use `from h3.api import basic_int as h3` at existing H3 call sites. Validate
  integer type, rejecting booleans, before H3 validity and configured resolution checks.
  Reuse the current portable canonicalization helper rather than adding a new identity subsystem.
- **Rationale**: `eligibility/cells.py` currently accepts hex strings, converts them with
  `h3.str_to_int` for sorting, and converts back with `h3.int_to_str`; models, candidate keys,
  ledger rows, and output schemas also carry hex strings. This existing path proves conversion
  already exists, but it is unnecessary with the integer-native API. A local check in the selected
  environment (h3-py `4.5.0`) confirmed `latlng_to_cell` returns Python `int`; the integer API
  includes boundary, centroid, covering, grid, and resolution operations.
- **Sources**: [h3-py API variants](https://uber.github.io/h3-py/api_comparison.html);
  [integer API source](https://github.com/uber/h3-py/blob/master/src/h3/api/basic_int/__init__.py).
- **Alternatives considered**: Keep hex internally and convert only at publication (does not
  standardize durable keys); store both forms (retains duplicate identity and extra payload).

## Numeric and Columnar Data Representation

- **Decision**: Use typed unsigned 64-bit H3 fields in new Arrow/Parquet/GeoParquet schemas, and
  exact integer values in in-memory models and builder-owned records. Use the canonical numeric
  value for sorting, deduplication, key equality, fingerprints, and deterministic serialization.
- **Rationale**: Typed uint64 columns avoid textual hex fields and preserve the H3 index value
  exactly for portable consumers. The project already depends on PyArrow and uses it for schema
  and Parquet I/O.
- **Alternatives considered**: Retaining hex as a compatibility column conflicts with the
  single-representation requirement. Generic floating-point serialization is not exact for all
  64-bit values and is not allowed.

## SQLite Storage and Valid Cell Domain

- **Decision**: Use SQLite `INTEGER NOT NULL` endpoint columns with integer-storage checks and
  application H3 validation, retaining parameter binding and transactional unique-key claims.
  SQLite is a physical signed storage representation, not an unsigned column type.
- **Rationale**: Valid H3 cell indices have bit 63 clear, so their positive values fit signed
  64-bit SQLite integers without reinterpretation. The uint64 public contract does not require
  accepting arbitrary unsigned values that fail H3 validation. A local in-memory check stored
  `617711448445681663` as SQLite `typeof='integer'` and read it back unchanged; an Arrow uint64
  array also returned the exact value.
- **Sources**: [H3 index layout](https://h3geo.org/docs/core-library/h3Indexing/);
  [SQLite storage classes](https://sqlite.org/datatype3.html).
- **Alternatives considered**: Replacing SQLite, storing decimal/hex text, or using custom unsigned
  bit encodings would add complexity without benefiting the valid H3 cell domain.

## JSON, Fingerprints, and Integration Labels

- **Decision**: Serialize cell-indexed mappings as numerically sorted arrays of records containing
  integer H3 fields; keep expected keys as two-integer arrays and destination batches as integer
  arrays. Reject string endpoints on load. Use deterministic integer-valued JSON for hashes,
  retaining exact Python integers and no generic stringification of H3 values.
- **Rationale**: The local check confirmed JSON converts an integer object key into a decimal
  string. Therefore simply changing type hints leaves a persistent string identity unless mapping
  shape changes. Publication part `origin_ids` already uses arrays; preserve that shape with
  integers. H3 cells exceed the exact range of common floating-point JSON parsers (`2^53`), so
  consumers must preserve integer tokens rather than round or fall back to decimal strings.
- **Decision**: Map assignment-local opaque Network Analyst `Name` labels back to validated
  integer indices at the adapter boundary. Keep decimal directory labels as filesystem syntax
  only; authoritative partition identity remains integer columns and manifest origin arrays.
- **Rationale**: `network/solver.py` currently reconstructs logical keys with `str(origin_id)`
  and reads location-status names as strings. Those paths must use the same validated label map
  for solve and location results without leaking text identity to the coordinator.
- **Alternatives considered**: Integer JSON object keys do not survive JSON serialization.
  ArcGIS floating-point fields cannot safely carry all H3 values. A new mobile transport protocol
  is unnecessary for this builder-only change.

## Compatibility and Shared Consumer Contract

- **Decision**: Version affected durable, publication, and shared contract identities. Update the
  builder's canonical shared contract and require a coordinated update in `knu2xs/h3-route-solver`
  before integer-keyed datasets are advertised as consumable.
- **Rationale**: Feature 004 currently specifies hex-string endpoint fields, with an optional
  integer alternate. Replacing field identities and types is incompatible. Versioning prevents
  clients from interpreting one schema as the other.
- **Version decision**: Proposed publication dataset, cell, fact, and shared-contract version is
  `2.0.0`; new eligibility schema, ledger format, work-ID and compatibility encodings use `2`.
  Keep GeoParquet `1.1.0`. Consumer adoption of the proposed contract remains a release dependency.
- **Alternatives considered**: Reusing the existing version or dual-writing aliases would make
  old and new consumers ambiguous and preserve the unwanted representation.

## Legacy State and Historical Publications

- **Decision**: Do not migrate legacy working ledgers. Detect them as incompatible and require an
  explicit fresh ledger and rebuild. Preserve the old ledger file unless an operator separately
  chooses to remove it. Keep historical publications unchanged and distinguish them by their
  original schema version.
- **Rationale**: The builder is pre-alpha and the user has accepted lossy reset/rebuild. Translating
  partially committed work risks corrupting Feature 003 uniqueness and fencing guarantees, while
  immutable publication is a constitution requirement.
- **Detection decision**: Check existing ledger metadata/schema using a read-only connection
  before WAL or initialization statements. Missing old format metadata or TEXT endpoint columns
  identify legacy state. Version eligibility fingerprints/run metadata too: old stages cannot be
  reused merely because candidate counts or filenames match.
- **Alternatives considered**: Lossless migration has unnecessary recovery, verification, and
  rollback complexity for pre-alpha state. Rewriting published files violates Feature 004.

## Efficiency and Scope

- **Decision**: Record reduced representation/storage/transfer overhead, including use on phones,
  as motivation only. Do not add a numeric performance target, benchmark infrastructure, mobile
  application, or device-specific encoding.
- **Rationale**: The requested change is narrowly a canonical representation standard; a
  quantitative efficiency claim requires separately scoped measurement.
- **Alternatives considered**: A device-specific transport or performance feature would expand
  beyond the builder/consumer data contract.
