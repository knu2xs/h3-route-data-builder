# Feature Specification: H3 Geometry Eligibility Spike

**Feature Branch**: `001-geometry-spike`

**Created**: 2026-10-06

**Status**: Draft

**Input**: User description: "Specify the geometry spike for the H3 Route Data Builder using `docsrc/mkdocs/design/builder/001-aoi-cell-generation-and-snapping.md` and the project constitution. Cover AOI validation, eligible transportation edges, H3 cells intersecting those edges, deterministic on-network representatives, Network Analyst location fields, and evidence of eligibility. Make it explicit that cells without an eligible edge must not enter OD planning. Include testable acceptance criteria for crossings, boundary touches, coincident boundaries, restrictions, one-way and multipart edges, and pentagon-adjacent cells. Keep candidate generation and OD solving out of scope."

## Clarifications

### Session 2026-10-06

- Q: If an edge’s travel-mode or restriction eligibility cannot be determined from the available data, how should the geometry spike handle it? → A: Exclude the uncertain edge, record the reason, and continue processing other edges.
- Q: What should happen when eligible-cell processing reaches a configured limit? → A: Do not silently omit eligible input; only mark the run complete after all expected input is reconciled, and leave it incomplete if a required total cap is exceeded.
- Q: Which project policy governs spatial operations for this feature? → A: Follow the builder-specific spatial-operation policy and leave the separate solver project unchanged.
- Q: Should validation include the provided real network data when it is available? → A: Yes, use it for optional read-only validation while keeping synthetic acceptance tests required.

## User Scenarios & Testing

### User Story 1 - Identify Network-Eligible Cells (Priority: P1)

As a builder operator, I need a validated AOI and a reproducible set of H3 cells that intersect transportation edges usable under the selected travel mode and restrictions, so that only cells with a real network basis proceed to later work.

**Why this priority**: Eligibility determines the sparse correctness of the dataset. A false positive creates invalid work; a false negative drops valid network coverage.

**Independent Test**: Run a synthetic AOI and transportation network with known crossings, touches, non-intersections, restrictions, one-way edges, multipart geometry, and pentagon-adjacent cells. Compare the resulting eligible cell IDs against the specified intersection and traversal rules.

**Acceptance Scenarios**:

1. **Given** a non-empty, valid polygon AOI with a declared CRS, **When** the geometry spike validates it, **Then** it accepts the AOI and evaluates geometry in the explicitly selected working CRS.
2. **Given** an empty, invalid, non-polygonal, or CRS-unknown AOI, **When** validation runs, **Then** it rejects the AOI with a reason and does not guess or silently repair its CRS or geometry.
3. **Given** an eligible edge whose in-AOI geometry crosses the interior of an H3 cell, **When** cell eligibility is evaluated, **Then** that cell is eligible.
4. **Given** an edge that only touches an H3 cell at a point or follows part of its boundary, **When** eligibility is evaluated under the declared inclusive intersection policy, **Then** the cell is eligible.
5. **Given** an edge that is close to a cell but has no geometric intersection with it, **When** eligibility is evaluated, **Then** the cell is not eligible.
6. **Given** an edge prohibited by the selected travel mode or an applicable restriction, **When** eligibility is evaluated, **Then** that edge does not make any cell eligible; a separate eligible intersecting edge may still qualify the same cell.
7. **Given** a one-way edge, **When** eligibility is evaluated, **Then** it qualifies only for the travel direction(s) permitted by the selected mode and restrictions, and its direction is not treated as bidirectional.
8. **Given** a multipart edge with an intersecting part and a non-intersecting part, **When** eligibility is evaluated, **Then** all parts are considered, each qualifying H3 ID appears once, and non-intersecting cells remain ineligible.
9. **Given** H3 cells at or adjacent to a pentagon, **When** canonical cell polygons and intersections are evaluated, **Then** each intersecting cell is handled by its canonical H3 ID without assuming six neighbors, dropping a cell, or producing duplicate IDs.
10. **Given** an AOI containing no eligible transportation edge, **When** eligibility completes, **Then** it produces no solvable cells and no cells are handed to OD planning.
11. **Given** an edge whose travel-mode or restriction eligibility cannot be determined, **When** eligibility is evaluated, **Then** that edge is excluded with a recorded reason and evaluation continues for other edges.
12. **Given** eligible input spans multiple partitions, **When** eligibility is processed, **Then** every expected input partition is evaluated deterministically and no eligible input is omitted because of processing limits.
13. **Given** a configured processing limit is reached before all expected input is complete, **When** processing ends, **Then** the run is incomplete and is not reported as a successful result.
14. **Given** the same H3 cell or representative candidate occurs in more than one input partition, **When** results are combined, **Then** the H3 cell appears once and its representative is selected by the defined deterministic rule, independent of input ordering.
15. **Given** all expected input has been processed, **When** eligibility results reconcile, **Then** and only then is the eligibility dataset marked complete.
16. **Given** a configured total-output hard cap is exceeded, **When** processing reaches the cap, **Then** the run fails explicitly, remains incomplete, and no partial result is marked or published as complete.
17. **Given** a run is configured without a total-output hard cap, **When** processing is requested, **Then** the configuration is rejected before eligibility processing begins.
18. **Given** the provided real network data is available, **When** local validation uses it, **Then** the source data remains unchanged and the synthetic acceptance suite remains independently runnable and required.

### User Story 2 - Audit Cell Representatives and Eligibility (Priority: P1)

As a data reviewer, I need one deterministic representative on an eligible edge for every eligible cell, together with network-location fields and evidence, so that each eligibility decision can be checked and reproduced.

**Why this priority**: A cell is not usable downstream merely because its polygon intersects a line; it must have a defensible network location and traceable eligibility evidence.

**Independent Test**: Repeat the same synthetic geometry evaluation and compare cell classifications, chosen edge identity, representative coordinates, snap distance, Network Analyst location fields, and eligibility evidence.

**Acceptance Scenarios**:

1. **Given** an eligible cell intersecting one or more eligible edges, **When** its representative is selected, **Then** exactly one point lies on an eligible intersecting edge portion within the AOI and is nearest to the cell centroid.
2. **Given** multiple eligible points are equally near the cell centroid, **When** the representative is selected, **Then** ties are resolved in order by network source ID, source object ID, and edge measure, independent of input ordering.
3. **Given** an eligible representative, **When** network location information is recorded, **Then** `SourceID`, `SourceOID`, `PosAlong`, and `SideOfEdge` identify its source edge and position and are valid for that network source.
4. **Given** the selected representative, **When** snap distance is checked, **Then** its distance from the eligible edge is zero within the explicitly configured tolerance.
5. **Given** any cell classification, **When** eligibility results are reviewed, **Then** the record identifies its eligibility status and reason and, for eligible cells, the intersecting eligible edge identity, representative coordinates, snap distance, Network Analyst location fields, and the policy context needed to reproduce the decision.
6. **Given** a cell with no eligible intersecting edge or no valid on-network representative, **When** results are handed to the next pipeline stage, **Then** the cell is marked ineligible and is absent from OD-planning input.

## Edge Cases

- AOI is empty, invalid, non-polygonal, or lacks a declared CRS.
- An edge crosses a cell, touches only at a vertex, coincides with a cell boundary, or lies nearby without touching.
- The only intersecting edge is restricted or prohibited for the selected travel mode.
- An edge's travel-mode or restriction eligibility cannot be determined from available data.
- A processing limit is reached before all expected input is evaluated, or the total-output hard cap is exceeded.
- The same H3 cell occurs in multiple input partitions, or an expected partition is missing from the final result.
- A one-way edge is accessible in one direction but prohibited in the reverse direction.
- A multipart edge has multiple parts with different intersection outcomes.
- Multiple eligible edges produce equal-distance representative candidates.
- AOI or edge geometry ends exactly on an AOI boundary; only the in-AOI edge portion contributes to eligibility and representative selection.
- An AOI has no eligible edge, or a cell intersects only ineligible edges.
- A cell is a pentagon or adjacent to a pentagon, where ordinary six-neighbor assumptions are not valid.
- A cell has an eligible geometric intersection but location fields cannot be populated or validated; it must not be considered solvable.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST accept an AOI only when it is non-empty, valid, polygonal, and has a declared CRS. It MUST reject invalid inputs with a reason and MUST NOT guess a missing CRS.
- **FR-002**: The system MUST evaluate spatial relationships in an explicitly selected working CRS and record the source and working CRS used for the result.
- **FR-003**: The system MUST determine edge eligibility from the selected travel mode and applicable restrictions, including direction-specific access. An edge prohibited for the evaluated travel direction MUST NOT establish cell eligibility. If eligibility cannot be determined, the system MUST exclude that edge, record the reason, and continue evaluating other edges.
- **FR-004**: The system MUST limit edge geometry used for intersection and representative selection to the portion within the AOI.
- **FR-005**: The system MUST generate canonical H3 cell polygons at the explicitly selected resolution for the relevant AOI scope, identify cells intersecting eligible in-AOI edge geometry, and deduplicate cell IDs.
- **FR-006**: The intersection policy MUST be explicit and recorded. For this spike, the policy MUST be inclusive: interior crossings, point touches, and coincident line/boundary portions count as intersections. Proximity without intersection MUST NOT count.
- **FR-007**: The system MUST consider every part of multipart edge geometry and MUST apply the same eligibility and intersection rules to each part.
- **FR-008**: The system MUST handle pentagon and pentagon-adjacent cells using canonical H3 cell identity and geometry, without relying on a fixed six-neighbor assumption.
- **FR-009**: Every eligible cell MUST have exactly one deterministic representative on an eligible intersecting edge portion within the AOI. The representative MUST be nearest to the cell centroid; ties MUST be resolved by source ID, source object ID, then edge measure.
- **FR-010**: The representative's snap distance MUST be zero within an explicitly configured tolerance. A cell without a valid representative MUST be ineligible.
- **FR-011**: Every eligible representative MUST have valid Network Analyst location fields `SourceID`, `SourceOID`, `PosAlong`, and `SideOfEdge` that identify its network source and position.
- **FR-012**: The system MUST record eligibility status and reason for each evaluated cell. For eligible cells it MUST record the intersecting eligible edge identity, representative coordinates, snap distance, Network Analyst location fields, H3 resolution, CRS context, travel mode and restrictions, intersection policy, and representative tie-breaking policy.
- **FR-013**: Only cells with `eligibility_status=solvable` and a validated representative MAY be exposed as eligible output. A cell without an eligible intersecting edge MUST NOT enter OD planning under any circumstance.
- **FR-014**: Repeated runs with identical AOI, network, travel mode, restrictions, CRS, H3 resolution, and policies MUST produce the same eligible cell IDs, edge selections, representative coordinates, and location fields, regardless of input feature ordering.
- **FR-015**: Candidate generation, candidate expansion, OD solving, cost calculation, and final publication are outside this feature. The feature ends at validated, auditable eligibility output whose expected inputs and completion state have been reconciled.
- **FR-016**: The system MUST evaluate every expected input partition deterministically and MUST NOT silently omit eligible input when a processing limit is reached. Processing limits MUST be explicit and recorded with the run evidence.
- **FR-017**: If a processing limit prevents completion of expected input, the system MUST leave the run incomplete and MUST NOT report partial results as complete.
- **FR-018**: The system MUST produce one result per canonical H3 cell and select exactly one deterministic representative per eligible cell, independent of input partition or feature ordering.
- **FR-019**: The system MUST reconcile all expected input partitions and eligibility results before marking the dataset complete. A run with missing or unreconciled input MUST remain incomplete.
- **FR-020**: Every run MUST require a configured total-output hard cap. If the cap is exceeded, the system MUST fail explicitly, leave the run incomplete, and MUST NOT report partial output as complete.
- **FR-021**: When the provided real network data is available, the system MUST support read-only validation against it. Synthetic acceptance tests MUST remain required and MUST NOT depend on the external dataset.

### Key Entities

- **AOI**: The valid polygonal geographic scope, including its declared CRS.
- **Transportation edge**: A network edge geometry with source identity, object identity, and travel-mode/restriction/direction eligibility.
- **H3 cell**: A canonical H3 cell ID and polygon at the selected resolution.
- **Representative**: The single deterministic point on an eligible in-AOI edge selected for an eligible cell, with its snap distance and network location fields.
- **Eligibility evidence**: The status, reason, intersecting edge identity, representative and location details, and policy context supporting the cell decision.
- **Eligibility run**: The expected input partitions, applicable processing limits, reconciled eligibility results, and incomplete or complete state for one evaluation.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Across the specified synthetic acceptance fixtures, 100% of cell classifications agree with the declared inclusive topology and travel eligibility rules, including zero eligible cells supported only by a non-intersecting or prohibited edge.
- **SC-002**: 100% of cells marked solvable have exactly one deterministic, validated network representative on an eligible in-AOI edge and snap distance within the configured zero tolerance.
- **SC-003**: Zero cells without an eligible intersecting edge or valid representative appear in OD-planning input, including when the AOI contains no eligible edges.
- **SC-004**: Repeated runs with identical inputs produce identical eligible cell IDs, selected edge identities, representative coordinates, and location fields.
- **SC-005**: For every successful run, 100% of expected input partitions are evaluated and reconciled, no eligible input is silently omitted, and each H3 ID appears once in the result.
- **SC-006**: A run is marked complete only when every expected partition reconciles; when a configured total-output hard cap is exceeded, the run fails explicitly and remains incomplete.
- **SC-007**: When real network data is available for local validation, all configured sample checks pass and the source data remains unchanged.

## Assumptions

- The selected travel mode, restrictions, H3 resolution, working CRS, snap tolerance, and tie-breaking rules are explicit inputs or configuration and are recorded with eligibility results.
- “Intersects” uses inclusive topological semantics for this spike: crossing, point touch, and coincident boundary line all qualify; proximity alone does not.
- The AOI defines the spatial scope. Only portions of eligible edges within the AOI may establish cell eligibility or host representatives.
- A one-way edge is eligible only in its permitted direction(s); this feature does not make a directional edge bidirectional.
- The geometry spike provides eligibility and representative results to a later stage but does not generate candidates or solve OD pairs.
- Processing limits MUST NOT silently omit eligible input. Every run requires an explicit total-output hard cap; exceeding it fails the run without a complete result.
- Spatial operations follow this builder's project policy. Non-spatial eligibility and run-state behavior remain separately testable; the solver project remains governed by its own policy.
- The provided real network data may be used for optional read-only local validation; it supplements, but never replaces, synthetic acceptance fixtures.
