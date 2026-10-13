# Published Dataset Contract

This contract defines the Feature 004 public dataset boundary. Feature-owned inputs and output
ownership are detailed in the [Feature 004 spec](../spec.md) and [data model](../data-model.md).

## Logical Tables

The dataset contains two logical tables:

1. `solvable_cells`: one record per canonical solvable endpoint in the selected Feature 002
   origin/destination cell scopes.
2. `od_facts`: one record per qualifying directed route or Feature 002 self-pair.

Cell, centroid, and representative geometry belong only to `solvable_cells`. `od_facts` carries
endpoint identifiers, not endpoint geometry. Non-route classifications are reconciliation
dispositions, not rows in `od_facts`.

## Schema Versions and Canonical Fields

The dataset manifest identifies the dataset schema version, each logical table schema version,
and GeoParquet version. The GeoParquet version is `1.1.0`. A change to field identity, type,
nullability, units, geometry semantics, or key meaning that is not backward-compatible requires a
new schema version.

### `solvable_cells`

| Field | Type | Nullability | Contract |
|---|---|---|---|
| `h3_id_hex` | UTF-8 string | Required | Canonical lowercase H3 identifier; unique |
| `h3_id_uint64` | unsigned 64-bit integer | Nullable | Alternate consumer representation when safely representable |
| `resolution` | unsigned 8-bit integer | Required | Must match `h3_id_hex` |
| `cell_geometry` | Polygon WKB | Required | Canonical H3 polygon |
| `centroid_geometry` | Point WKB | Required | Canonical H3 centroid |
| `representative_geometry` | Point WKB | Required | Feature 001 deterministic network representative |
| `intersecting_edge_count` | unsigned 32-bit integer | Required | Nonnegative count of distinct eligible intersecting edges |
| `network_source_id` | signed 32-bit integer | Required | Representative Network Analyst source ID |
| `network_source_oid` | signed 64-bit integer | Required | Representative source object ID |
| `network_pos_along` | 64-bit float | Required | Finite normalized position along network source |
| `network_side_of_edge` | signed 8-bit integer | Required | Validated Network Analyst side-of-edge value |
| `representative_snap_distance_m` | 64-bit float | Required | Finite, nonnegative meters |
| `eligibility_status` | UTF-8 string | Required | Exactly `solvable` |
| `eligibility_reason` | UTF-8 string | Required | Feature 001 reason code or description |
| `eligibility_fingerprint` | UTF-8 string | Required | Feature 001 evidence and policy identity |

All three geometry fields are root-level, non-repeated geometry columns in WKB encoding. Their
GeoParquet metadata declares their actual geometry type, WGS 84 / EPSG:4326 PROJJSON, and usable
bounding-box or covering metadata. The manifest records deterministic spatial ordering and
geometry extent conventions.

### `od_facts`

| Field | Type | Nullability | Contract |
|---|---|---|---|
| `origin_h3_id_hex` | UTF-8 string | Required | Canonical solvable origin H3 identifier |
| `destination_h3_id_hex` | UTF-8 string | Required | Canonical solvable destination H3 identifier |
| `travel_mode` | UTF-8 string | Required | Configured compatible travel mode |
| `network_distance_m` | 64-bit float | Nullable | Actual network distance in finite, nonnegative meters when available |
| `network_time_s` | 64-bit float | Nullable | Actual network time in finite, nonnegative seconds when available |
| `origin_representative_snap_distance_m` | 64-bit float | Required | Finite nonnegative value from cell dimension |
| `destination_representative_snap_distance_m` | 64-bit float | Required | Finite nonnegative value from cell dimension |
| `solve_status` | UTF-8 string | Required | Exactly `solved` or `self_pair` |
| `work_item_id` | UTF-8 string | Nullable | Null only for self-pairs |
| `build_fingerprint` | UTF-8 string | Required | Compatible Feature 003 result fingerprint |

At least one actual network cost is present, and the configured actual impedance cost is required
for solved routes. Both costs are zero for self-pairs. No geometry is stored in this table.

## Key and Outcome Rules

- The unique logical fact key is the ordered pair
  `(origin_h3_id_hex, destination_h3_id_hex)`. Direction matters.
- A non-self fact must match exactly one compatible Feature 003 committed qualifying outcome and
  both endpoints must resolve to one `solvable_cells` row.
- A self-pair produces one zero-cost fact and requires no solve work item.
- `unlocated`, `unreachable`, and `cutoff-excluded` dispositions are counted and described in
  reconciliation metadata but never serialized as route facts.
- Feature 002 prefilter-pruned keys are excluded from expected-key reconciliation and facts; the
  count and candidate-policy provenance remain in the dataset manifest.
- AOI-wide mode consumes every in-AOI pair retained by Feature 002's conservative prefilter. The
  configured actual-cost cutoff continues to determine qualifying facts.
- Missing, duplicate, unexpected, incompatible, retryable, unresolved, or terminal-failure keys
  prevent complete publication.

## Partitioning and Pruning

Fact data is logically partitioned by canonical origin H3 identifier. The origin column remains
typed in fact rows and origin partition metadata remains authoritative even if compaction combines
multiple origins in a physical file. File/row-group metadata must allow a one-origin query to skip
unrelated origins. Cell rows have deterministic locality-preserving spatial ordering. Both
partition and ordering policies are recorded in the dataset manifest.

## Dataset and Partition Manifests

The dataset manifest records:

- Immutable version ID, creation time, publication state, dataset fingerprint, and result
  compatibility fingerprint.
- Feature 001 eligibility identity; Feature 002 mode, candidate/run provenance, and pruned-pair
  count; Feature 003 solve reconciliation state and outcome counts.
- Expected logical-key count, fact key count, solvable-cell row count, and resolved non-route
  counts.
- Table schema versions, GeoParquet 1.1.0 version, geometry CRS/covering conventions, partition
  scheme, spatial-ordering policy, and all required partition-manifest references.

Each partition manifest records its logical table and partition keys, immutable part locations,
checksum and named algorithm, row counts, schema versions, applicable geometry extents/CRS, and
reconcilable partition totals. Together the manifests support endpoint-membership, key-uniqueness,
and expected-key validation.

## Publication and Completion

1. Build immutable data parts and manifests in a staging version that consumers cannot discover
   as complete.
2. Validate schemas, GeoParquet metadata, CRS, geometry extents, checksums, row counts, manifest
   references, endpoint membership, key uniqueness, and expected-key reconciliation.
3. On any validation failure, record a visible incomplete/rejected state and do not expose a
   success marker.
4. Expose the fully validated immutable version through one atomic publication visibility
   operation. `_SUCCESS` or its equivalent is valid only for the matching complete manifest.

Consumers must reject a dataset without a valid completion marker and matching complete
manifest. Filenames, process status, or unreferenced parts never establish success.

## Compaction

Compaction produces a new immutable version and refreshed manifests. It may combine, split,
reorder, or rewrite physical parts, but preserves the exact logical rows, identifiers, values,
units, nullability, eligibility evidence, CRS, and publication semantics. It must retain enough
origin metadata for the pruning contract. The previous version is never modified in place.
