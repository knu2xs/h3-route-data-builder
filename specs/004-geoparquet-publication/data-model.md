# Data Model: GeoParquet Publication

This model defines the published logical records, immutable physical parts, and completion
evidence. Canonical field details are in the [publication contract](contracts/publication-contract.md)
and the [feature specification](spec.md).

## Solvable-Cell Dimension

One record represents each unique canonical solvable H3 cell in Feature 002's selected origin and
destination scopes. Membership is not reduced to cells referenced by retained logical keys.
Every published record has `eligibility_status=solvable` and valid Feature 001 eligibility
evidence.

Required data includes canonical lowercase `h3_id_hex`, nullable safe `h3_id_uint64`, resolution,
cell polygon, centroid, deterministic network representative, distinct eligible intersecting-edge
count, Network Analyst source/OID/position/side fields, representative snap distance in meters,
eligibility status/reason, and eligibility fingerprint. Polygon and point geometries are stored
here, not repeated in OD facts. All geometry uses WGS 84 / EPSG:4326.

**Identity and validation**

- `h3_id_hex` is unique after canonicalization and matches the configured resolution.
- Each row is solvable, has one valid deterministic representative and required eligibility
  evidence, and has finite nonnegative measurements.
- The three geometry columns have the declared GeoParquet 1.1.0 geometry types, WKB encoding,
  complete CRS PROJJSON, and usable extent/covering metadata.
- Dimension row count equals the distinct solvable cells in the selected Feature 002 endpoint
  scopes, including cells without retained pair references.

## Directed OD Fact

One record represents a qualifying non-self route or a Feature 002 self-pair. The logical identity
is the direction-sensitive ordered tuple
`(origin_h3_id_hex, destination_h3_id_hex)`. It is independent of work item, file, partition,
compaction, or dataset version.

Required data includes origin and destination IDs, travel mode, nullable actual network distance
in meters and time in seconds, both endpoint representative snap distances in meters, `solve_status`
(`solved` or `self_pair`), nullable `work_item_id` only for self-pairs, and the compatible
`build_fingerprint`. At least one actual cost is present; the cost selected by the configured
impedance is required. Estimates and stretch values are not network costs.

**Identity and validation**

- Exactly one row exists per fact key; reverse-direction routes are separate keys.
- Both endpoints resolve to exactly one dimension row.
- A non-self fact refers to one compatible Feature 003 committed qualifying outcome.
- A self-pair has zero network cost and no network work item.
- No geometry column is present in the fact table.

## Expected-Key Reconciliation

The expected publication key set contains Feature 002 retained non-self candidate keys and
self-pairs. Pairs removed by Feature 002's conservative prefilter are excluded and their count and
policy provenance are recorded in the dataset manifest.

Each retained non-self key has exactly one authoritative Feature 003 outcome:

- A qualifying outcome becomes one OD fact.
- `unlocated`, `unreachable`, or `cutoff-excluded` is a resolved non-route disposition, counted
  in reconciliation and not written as an OD fact.
- Retryable, unresolved, terminal system failure, missing, duplicate, unexpected, or incompatible
  outcomes prevent successful publication.

Facts equal qualifying non-self outcomes plus self-pairs exactly. A successful publication
accounts for each expected key once as either a fact or a resolved non-route disposition.

## Dataset Manifest

One manifest identifies one immutable logical dataset version. It records publication/completion
state, creation time, dataset and result compatibility fingerprints, Feature 001 eligibility
fingerprint, Feature 002 candidate mode and provenance, Feature 003 reconciliation state, expected
and published key counts, dimension row count, non-route outcome counts, prefilter-pruned count,
schema identifiers and versions, GeoParquet version, CRS and covering conventions, partition
scheme, spatial-ordering policy, and every dimension/fact partition-manifest reference.

The manifest status cannot say successfully published until every required table, key, partition,
part, and checksum passes validation. An incomplete or corrupt state remains explicit.

## Partition Manifest and Data Part

A partition manifest belongs to either the cell dimension or OD facts and records logical
partition keys and totals. Each immutable data-part reference carries a relative location,
checksum and algorithm, row count, schema version, and applicable geometry extent/CRS. Manifest
totals reconcile to referenced files and rows exactly.

OD fact partitions are keyed by canonical solvable origin H3. The origin remains a typed row field
and is present in partition metadata. Physical compaction may place multiple origins in a file,
but row-group or equivalent metadata must still allow an equality filter on one origin to skip
unrelated data. Cell rows use a deterministic, locality-preserving spatial order whose policy and
version are recorded.

## Publication Version and Completion Marker

A publication version groups its logical tables, parts, manifests, and optional `_SUCCESS` marker.
Staging and incomplete versions are not successful datasets. The marker is valid only with a
matching complete manifest and after the one atomic publication visibility operation. File names,
worker status, and unreferenced data parts are not completion evidence.

## Compacted Version

Compaction creates a new immutable physical version with updated part references, row counts,
checksums, extents, and manifests. It preserves every logical dimension row and OD fact, all
identifiers and typed values, units, nullability, eligibility evidence, CRS, and outcome semantics.
The previous published version and its parts remain unchanged.
