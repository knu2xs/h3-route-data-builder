# Feature 001: Network-Intersecting Solvable Cells

Feature 006 standardizes new cell identities as exact integer `h3_id` values. Eligibility
working schemas/fingerprints are version 2, with required `uint64` staged columns.
Legacy stages and completed runs are not adopted; rebuild in a fresh output location.
Geometry, membership, and representative policy below are unchanged.

## Requirements

1. Accept and validate an AOI.
2. Select transportation edges eligible under the travel mode and restrictions.
3. Generate canonical H3 polygons intersecting eligible edges in the relevant scope.
4. Deduplicate H3 IDs and confirm polygon-edge intersection.
5. Define explicitly whether boundary touching counts.
6. Select a deterministic representative point on an eligible intersecting edge.
7. Calculate/preserve Network Analyst location fields.
8. Record eligibility and representative evidence.
9. Exclude every nonintersecting cell from OD planning.
10. Reuse compatible cells when coverage expands.

## Acceptance

Every OD-eligible cell intersects an eligible edge and has a valid on-network representative. Tests cover crossings, touches, coincident boundaries, restrictions, one-way edges, multipart geometry, and pentagon-adjacent cells.
