# Data Model: H3 Geometry Eligibility Spike

## AOI

The Area of Interest defines the geometry scope for edge clipping and cell evaluation.

| Attribute | Meaning | Validation |
|---|---|---|
| `aoi_geometry` | Non-empty polygonal geometry | Must be valid; do not silently repair |
| `source_crs` | Declared CRS of AOI input | Required; unknown CRS is rejected |
| `working_crs` | Configured projected CRS for topology and distance | Required, appropriate for AOI, recorded in run evidence |
| `storage_crs` | Configured CRS for persisted GeoParquet geometries | Required and recorded in run evidence; storage transforms happen after measurement |

The AOI and edge inputs are explicitly transformed to the working CRS. H3 boundaries are interpreted in H3's latitude/longitude coordinate order and transformed with GIS x/y order. Edge geometry outside the AOI is excluded before intersection and representative selection. Persisted cell, centroid, and representative geometries are projected to the configured storage CRS after all measurements are complete.

## Transportation Edge

An edge is an input network source feature eligible or ineligible under one travel mode and its restrictions.

| Attribute | Meaning | Validation |
|---|---|---|
| `source_id` | Network Analyst network-source identifier | Must map to the selected network source |
| `source_oid` | Source feature object ID | Stable for the network build; retained as evidence |
| `geometry_working` | Edge portion within the AOI in working CRS | Multipart parts all evaluated |
| `eligibility_status` | Eligible, restricted, or undetermined | Undetermined fails closed |
| `eligibility_reason` | Reason for status | Recorded for excluded edges |
| `travel_direction` | Direction(s) permitted by selected mode/restrictions | Must not infer bidirectional access |

An edge is eligible only if its direction and restrictions permit travel under the selected configuration. Unknown or prohibited edges cannot establish a solvable cell.

## H3 Cell and Eligibility Result

One reconciled result row exists per canonical H3 ID across all input partitions.

| Attribute | Meaning | Validation |
|---|---|---|
| `h3_id_hex` | Canonical H3 cell identifier | Unique after global reconciliation |
| `resolution` | H3 resolution | Must equal configured resolution |
| `cell_geometry` | Canonical cell polygon in working CRS | Valid polygon geometry |
| `centroid_geometry` | Cell centroid in working CRS | Used only for deterministic representative ranking |
| `eligibility_status` | `solvable` or `ineligible` | Only `solvable` may enter later OD planning |
| `eligibility_reason` | Primary decision reason | Required for every evaluated cell |
| `intersecting_edge_count` | Unique eligible edge identities intersecting the cell | Zero for cells without eligible intersections |
| `build_fingerprint` | Fingerprint of inputs and behavior-affecting policy | Consistent across a run |

A cell is `solvable` only if at least one eligible in-AOI edge has an inclusive topological intersection with its polygon and the selected representative has valid network location fields. If a cell is eligible in any partition, the reconciled global result is solvable; intersecting eligible edge identities are deduplicated before representative selection.

## Representative and Network Location

Exactly one representative is persisted for each solvable cell.

| Attribute | Meaning | Validation |
|---|---|---|
| `representative_geometry` | Point on the selected eligible intersecting edge within the AOI | Must lie on that edge within configured zero tolerance |
| `representative_snap_distance_m` | Distance from representative to selected edge | At or below configured tolerance |
| `SourceID` | Network source identifier | Must match a qualifying eligible edge |
| `SourceOID` | Network source object identifier | Must match a qualifying eligible edge |
| `PosAlong` | Position along source edge | Must identify the representative location |
| `SideOfEdge` | Network Analyst side-of-edge value | Must be valid for the identified source |

Rank eligible representative candidates by distance from the cell centroid, then `SourceID`, `SourceOID`, and edge measure. Validate the Network Analyst location result against that selected edge; reject mismatches and try the next ranked candidate. Ineligible cells have no representative or Network Analyst location values.

## Eligibility Run and Partitions

A run captures the immutable policy context and lifecycle for a complete AOI evaluation.

| Attribute | Meaning |
|---|---|
| `run_id` | Stable identifier for a logical input/policy combination |
| `input_fingerprint` | AOI, network, travel mode/restrictions, CRS, H3, eligibility policy, schema, and software identity |
| `schema_version` | Eligibility-result and staging schema version |
| `software_versions` | Python, ArcGIS Pro, H3, and package versions used by the run |
| `expected_partition_keys` | Deterministically ordered input partitions planned for the run |
| `partition_status` | `pending`, `processing`, `staged`, `reconciled`, or `failed` |
| `part_key` | Stable logical identity for one bounded output part |
| `part_row_count` | Rows in staged part; must not exceed configured per-part limit |
| `part_checksum` | Content checksum used for idempotent reconciliation |
| `run_status` | `processing`, `failed_incomplete`, or `complete` |
| `unique_solvable_cell_count` | Count checked against the required total-output hard cap |

A run becomes `complete` only after every expected input partition and staged part reconciles, H3 IDs are globally deduplicated, and representatives are deterministic. A total-cap overflow or missing/unreconciled partition leaves `run_status=failed_incomplete`; staged parts are not exposed as a complete eligibility result.

## Relationships and Invariants

- An AOI evaluation has one run; a run has many input partitions and staged parts.
- A cell may intersect multiple eligible edges but has one globally selected representative.
- Many staging parts may contain evidence for the same H3 ID; reconciliation emits one result row per H3 ID.
- A `solvable` result has at least one eligible intersecting edge and exactly one validated representative.
- An `ineligible` result has a reason and cannot appear in the OD-planning handoff.
- The required total-output cap counts unique `solvable` H3 IDs, not staging duplicates or ineligible audit rows.
