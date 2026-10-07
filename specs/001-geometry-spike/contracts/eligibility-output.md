# Eligibility Output Contract

## Purpose and Boundary

This is the internal contract between geometry eligibility and later builder stages. It maps to
[the shared solvable-cell data contract](../../../docsrc/mkdocs/design/03-data-contract.md) without
changing that shared contract. This feature does not create OD candidates, solve OD pairs, calculate
network costs, or publish the final dataset.

## Inputs

- A non-empty valid polygon AOI with declared source CRS.
- A network dataset and edge-source identities/geometries.
- An explicit working CRS, H3 resolution, travel mode, restrictions, intersection policy,
  representative policy, snap tolerance, deterministic input partitioning, per-part limit, and
  required total-output hard cap.
- Policy and input fingerprints sufficient to identify the eligibility run.

Missing or unresolvable edge eligibility is treated as ineligible and recorded; it does not
invalidate other edges. Invalid AOI/CRS fails the run before eligibility output is produced.

## Eligibility Result Rows

The audit result contains one globally reconciled row per evaluated canonical `h3_id_hex`.
Required fields align with the shared contract: `h3_id_hex`, resolution, cell geometry, centroid
geometry, network representative geometry when solvable, intersecting-edge count, network source
and OID, percent along, side of edge, representative snap distance, eligibility status, and build
fingerprint. Each row also includes an eligibility reason. Network location field names at the
ArcGIS handoff are `SourceID`, `SourceOID`, `PosAlong`, and `SideOfEdge`.

- `eligibility_status=solvable`: at least one eligible traversable edge intersects the cell under
  the inclusive topology policy, and one deterministic representative has been validated on such
  an edge. Exactly one result row and one representative exist for the H3 ID.
- `eligibility_status=ineligible`: no eligible intersecting edge exists, eligibility could not be
  determined, or no valid representative/location could be produced. The reason is present and
  representative/location fields are null.

When several eligible edges or parts intersect one cell, `intersecting_edge_count` counts unique
network source/OID identities. Select the representative by centroid distance, then `SourceID`,
`SourceOID`, and edge measure. Input and part ordering must not affect the result.

## Staging Parts and Reconciliation

- Each deterministic bounded batch writes to its own staging part, with a stable part key, row
  count, schema/policy fingerprint, and checksum.
- A part exceeding its configured per-part row limit is deterministically subdivided and retried;
  no row is silently dropped. Any unrecoverable part-write failure leaves the run incomplete.
- Reconciliation merges evidence by canonical H3 ID, deduplicates cells globally, and emits one
  result row per H3 ID. A cell supported by any eligible intersecting edge is `solvable` even if
  other partitions contain only ineligible edge evidence for that same cell.
- The required total-output hard cap counts distinct solvable H3 IDs. Exceeding it fails the run
  explicitly and leaves it incomplete; staged results are never labeled complete.
- Run state may become `complete` only after expected input partition keys and all staged parts
  reconcile. Missing partitions, checksum mismatch, or failed reconciliation prevent completion.

## OD-Planning Handoff

The only admissible handoff is the filtered view where `eligibility_status=solvable` and all
representative and Network Analyst location fields validate. No ineligible row, missing-edge cell,
unresolved edge-eligibility cell, or cell lacking a valid representative may enter OD planning.
Candidate generation and OD solving consume this contract in later features and are not performed
here.
