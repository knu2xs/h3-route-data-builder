# Quickstart: H3 Geometry Eligibility Spike

This guide describes the validation workflow for the geometry eligibility feature. ArcPy-based
geometry/reprojection and Network Analyst checks require ArcGIS Pro. H3 indexing and non-spatial
staging/state checks can run in the project Python environment without ArcPy.

## Prerequisites

- Python environment matching the project (`make env` on Windows or the documented ArcGIS Pro
  clone).
- Project dependencies including H3 v4, PyArrow, and pytest.
- For geometry and network integration tests: ArcGIS Pro, Network Analyst, and synthetic AOI and
  network fixtures. ArcPy is supplied by ArcGIS Pro; Shapely and pyproj are not used.
- For the optional real-data smoke test: the supplied StreetMap Premium 2025 network dataset,
  readable by ArcPy in the local ArcGIS Pro environment.
- Configuration for an explicit area-appropriate `spatial.working_crs` and declared
  `spatial.storage_crs`; geometry tests must not
  rely on an implicit default CRS.

The feature configuration is expected to include explicit values for H3 resolution, travel mode,
restrictions, intersection policy, snap tolerance, deterministic batch sizing, per-part row limit,
and required total solvable-cell hard cap. The exact configuration key names are established in
implementation tasks; no values are hardcoded by this guide.

## Run Portable Checks

From the repository root, run H3 identity, non-spatial eligibility-state, and staging tests:

```powershell
pytest -q testing/test_eligibility_rules.py testing/test_eligibility_staging.py
```

These tests must import and run without ArcPy. Expected outcomes:

- H3 indexing and non-spatial eligibility-state rules produce the same IDs and statuses when input
  ordering changes.
- Part overflow subdivides and retries without truncation; cross-part duplicate IDs reconcile once.
- A missing partition or total hard-cap overflow leaves the run incomplete.

## Run ArcPy Geometry and Network Checks

In ArcGIS Pro with Network Analyst enabled, run the ArcPy-dependent spatial and network suites:

```powershell
pytest -q testing/test_eligibility_geometry.py testing/test_network_eligibility.py
```

The geometry fixtures use fixed H3 cell IDs, a fixed resolution, and expected eligible-ID sets
declared independently of function output. Construct line fixtures from canonical ArcPy cell
boundary geometries so each topology case has a known oracle:

| Fixture | Synthetic geometry | Expected result |
|---|---|---|
| `crossing` | Eligible line passes through a target cell interior | Target H3 ID is solvable |
| `point_touch` | Eligible line endpoint touches one cell vertex | Touched H3 ID is solvable |
| `coincident_boundary` | Eligible line follows a shared boundary between two cells | Both adjacent H3 IDs are solvable |
| `nearby_nonintersection` | Eligible line is separated from the cell boundary | Neither nearby cell is solvable |
| `restricted_only` | Only intersecting edge is prohibited | Cell is ineligible with restriction reason |
| `unknown_eligibility` | Intersecting edge eligibility cannot be determined | Cell is ineligible with recorded reason |
| `one_way` | Edge has a configured allowed direction and a prohibited reverse direction | Eligibility follows the configured travel direction |
| `multipart` | One part intersects a target cell and another part does not | Target ID occurs once; unrelated cell is ineligible |
| `pentagon_adjacent` | Fixed pentagon and adjacent-cell geometry at the fixture resolution | Exact intersecting ID set; no six-neighbor assumption |

The synthetic network fixture must include a restricted closest edge and a farther eligible edge,
plus one-way and multipart source features. The point fixture must lie on its intended intersecting
edge; assertions compare `SourceID`, `SourceOID`, `PosAlong`, and `SideOfEdge` with that edge. A
location assigned to another source/OID is rejected, not counted as a passing snap.

Spatial fixture assertions use ArcPy geometry and projection operations for crossing, point-touch,
coincident-boundary, nearby non-intersection, AOI clipping, multipart, and pentagon-adjacent cases.
ArcPy-dependent tests are marked and skipped when ArcPy is unavailable.

Expected outcomes:

- Eligible edge classification matches the test travel mode and restrictions; indeterminate edges
  are excluded with a reason.
- Calculate Locations fields identify the intended eligible edge and position. A location snapped
  to another source/edge is rejected rather than accepted as evidence.
- The representative lies on an eligible intersecting in-AOI edge within the configured tolerance.

## Run Real Network Smoke Test

The real-data test is read-only and separate from the required synthetic acceptance suite. Set the
network path for this local environment and run:

```powershell
$env:H3_RDB_TEST_NETWORK = 'D:\data\ba_data\usa_2025\Data\StreetMap Premium Data\northamerica.geodatabase\main.Routing\main.Routing_ND'
pytest -q testing/test_real_network_dataset.py
```

The test must use `arcpy.Exists` rather than an operating-system file check, confirm the dataset
exposes the `Driving Time` travel mode, and call `arcpy.na.CalculateLocations` on an in-memory
point at longitude -73.9857, latitude 40.7484. It must verify populated `SourceID`, `SourceOID`,
`PosAlong`, and `SideOfEdge` fields and leave the source geodatabase unchanged. Skip this test when
ArcPy or the configured dataset is unavailable.

## Acceptance Gate

Run the complete project test suite before merge:

```powershell
make test
```

A geometry run is successful only if all expected input partitions reconcile, globally deduplicated
solvable H3 IDs have exactly one validated representative each, and the run is marked complete only
after reconciliation. A total-cap overflow or partition failure must remain visibly incomplete;
there is no successful partial-result state.
