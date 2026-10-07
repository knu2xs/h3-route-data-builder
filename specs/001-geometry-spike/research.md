# Research: H3 Geometry Eligibility Spike

**Date**: 2026-10-06

## Decisions

### Geometry operations and CRS

- **Decision**: Use ArcPy geometry capabilities for AOI validation, constructing/projecting H3 cell polygons, clipping edge geometry to the AOI, exact intersections, and representative point/edge measurements. Keep these operations in network/geoprocessing modules. Use H3 v4 for cell IDs and boundary coordinates; keep H3 indexing, non-spatial status rules, and staging reconciliation ArcPy-free.
- **Rationale**: The builder is an ArcGIS Pro application and the user selected ArcPy geometry/reprojection as a project-specific requirement. A builder-specific amendment to Principle II permits this spatial dependency while the solver remains ArcPy-free. ArcPy's `Geometry.projectAs` performs explicit reprojection; `intersect` returns a geometric intersection, and `queryPointAndDistance` returns a nearest point, measure, distance, and side information.
- **Inclusive intersection rule**: Test ArcPy intersections at both dimension `1` (point/multipoint) and dimension `2` (polyline); the cell qualifies if either result is nonempty. A single dimension would miss either point-only touches or line crossings/coincident boundaries. The synthetic ArcPy fixtures are the acceptance oracle.
- **Alternatives considered**: Shapely for topology and pyproj for transformation; rejected by the clarified project requirement. Distance tolerance as a substitute for intersection; rejected because proximity must not qualify a cell.
- **Dependency impact**: No package additions. ArcPy is provided by the ArcGIS Pro environment; Shapely and pyproj are not used for this feature's geometry or reprojection.
- **CRS handling**: Reject missing input CRS. Project AOI, edges, and H3 cell geometries into configured `spatial.crs_working` with ArcPy; specify a datum transformation when the source and target datums require one. Record source/working CRS and transformation in run evidence.

### H3 cell coverage

- **Decision**: Generate a conservative H3 cell candidate superset for the AOI using the H3 v4 overlap-capable polygon coverage operation, using its `bbox_overlap` mode where supported. Construct canonical cell polygons from H3 boundary coordinates with ArcPy, project them into the working CRS, and use ArcPy geometry disjoint/intersection operations for the eligibility decision. Sort and deduplicate canonical H3 IDs before partitioning.
- **Rationale**: Center-contained polygon filling alone can miss cells that intersect only at a boundary. A deliberately broader cover is acceptable because it is not the eligibility predicate; exact topology removes false positives. Canonical IDs and geometry avoid assumptions that each cell has six neighbors.
- **Alternatives considered**: Treat the H3 polygon fill result as final; rejected because containment is not equivalent to intersection. Use fixed six-neighbor expansion; rejected because pentagons invalidate that assumption. Use a Shapely predicate as the final decision; rejected by the clarified ArcPy-only spatial-operation requirement.
- **Validation gate**: The implementation must prove the candidate cover contains every intersecting cell in synthetic crossing, point-touch, coincident-boundary, AOI-boundary, multipart, and pentagon-adjacent fixtures. If it misses any oracle cell, the cover strategy must change; the exact intersection rule must not be weakened.

### Network edge eligibility and Network Analyst fields

- **Decision**: Keep network feature access and travel-mode interpretation in an ArcPy/Network Analyst adapter. Resolve edge eligibility from the selected network, travel mode, restrictions, and direction; unknown classifications fail closed with a reason. Select geometric representatives only from eligible, intersecting, in-AOI edge portions.
- **Rationale**: ArcPy's read-only network-dataset Describe surface exposes network attributes, evaluator counts, source names, edge direction, evaluator type, and evaluator data. The adapter can support explicit field evaluators and known restriction-usage values, while rejecting unsupported expressions/types instead of inferring edge access. Turn-source restrictions affect transitions rather than globally blocking their source edge and are not treated as edge-wide prohibitions.
- **StreetMap Premium evaluator evidence**: The supplied network exposes edge source `main.Routing_Streets` (source ID 1). Its `Travel Direction` descriptor has evaluators `!FT_TRAVEL_DIRECTION! != 'N'` and `!TF_TRAVEL_DIRECTION! != 'N'`; the `Driving an Automobile` restriction uses `FT_RST_AUTOMOBILES` and `TF_RST_AUTOMOBILES` by direction. In the `Driving Time` mode, active restriction usage values observed are `-1` for prohibited, `2` for avoid-medium, and `5` for avoid-high. For example, gates use `2`, unpaved roads use `5`, and automobile access uses `-1`. Preserve only directions passing travel-direction evaluation and not blocked by a `-1` edge restriction. Values `2` and `5` affect preference/impedance but do not make an edge non-traversable. Unsupported values or missing fields make the edge undetermined.
- **Supported evaluator subset**: Parse ArcPy `Field` evaluator expressions as a restricted boolean/comparison expression over `!FIELD!` tokens and literal constants. Do not call `eval` or execute Script evaluators. Support equality/inequality comparisons and `and`, `or`, and `not`; unsupported syntax is indeterminate and therefore fails closed.
- **Location-field decision**: Use `arcpy.na.CalculateLocations` with the same network and travel mode/locate settings as the network adapter. Validate returned `SourceID`, `SourceOID`, `PosAlong`, and `SideOfEdge` against the representative's intended eligible edge and measure. Calculate Locations may select the next-closest valid edge under restrictions; therefore its result is not accepted solely because it returned location fields. A mismatch is rejected and the next deterministically ranked eligible edge candidate is tried; no valid match makes the cell ineligible.
- **Alternatives considered**: Trust nearest-edge location fields without checking source identity; rejected because the result can move to a different edge. Manually derive Network Analyst fields from geometry; rejected because source IDs, positions, side, and restriction-aware locating must match the network dataset.

### Deterministic batching and completion

- **Decision**: Process stable input partition keys serially in stable order. Give each bounded batch a stable logical key and its own staged spatial part. If a part exceeds its row limit, deterministically subdivide the input batch and retry. Reconciliation deduplicates by canonical H3 ID, merges all eligible edge evidence, then selects one representative by centroid distance and source ID, source OID, and edge measure. Require a total hard cap and count it against unique solvable H3 IDs. Reconcile all expected input partitions and staged parts before setting run state to `complete`.
- **Rationale**: This supports deterministic retries and idempotent staging, avoids truncation at per-part limits, and enforces constitution principles V, VII, IX, and XV. The required total hard cap is distinct from part sizing and leaves the run incomplete on overflow. Fingerprints also include schema and software versions as required by principle IV.
- **Alternatives considered**: Drop rows when a part limit is reached; rejected because it silently loses eligible cells. Mark each successful part as a complete dataset; rejected because other input partitions may be missing.

### Staging representation

- **Decision**: Stage each spatial part in GeoParquet using the existing solvable-cell geometry/CRS contract; persist run and partition reconciliation metadata separately from the part payloads. A part write is atomic, and its logical key, row count, and content checksum are recorded.
- **Rationale**: The project already depends on PyArrow and defines a GeoParquet consumer contract. Reusing that geometry representation avoids introducing a one-off staging schema. This is eligibility staging, not final publication.

### Real-data integration check

- **Decision**: Add a separate read-only ArcPy smoke test for the provided StreetMap Premium 2025 network. Resolve the network with `arcpy.Exists`, verify its `Driving Time` travel mode, and calculate Network Analyst location fields for a fixed point in an in-memory feature class. Keep synthetic acceptance tests mandatory; skip only the external-data test when ArcPy or the configured path is unavailable.
- **Evidence**: In the current `/env` Python 3.13 environment, ArcPy 3.7 Advanced reports the path exists, describes it as a Network Dataset in `GCS_WGS_1984`, and lists eight travel modes including `Driving Time`. `arcpy.na.CalculateLocations` completed for one in-memory point at longitude -73.9857, latitude 40.7484 and did not modify the source geodatabase.
- **Alternatives considered**: Require the external dataset for every test run; rejected because it is not shipped with the repository and would make tests depend on local licensed data. Treat the smoke test as a replacement for synthetic fixtures; rejected because real network data does not provide controlled crossing/touch/restriction oracles.

## Sources

- [Project constitution](../../.specify/memory/constitution.md), principles I-V, VII-IX, XI-XV.
- [Builder geometry design note](../../docsrc/mkdocs/design/builder/001-aoi-cell-generation-and-snapping.md).
- [Shared data contract](../../docsrc/mkdocs/design/03-data-contract.md).
- [ArcGIS Pro Calculate Locations documentation](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/network-analyst/calculate-locations.html): location fields, travel-mode-aware location search, and search criteria/query behavior.
- [ArcGIS Pro Get/Export Travel Modes documentation](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/network-analyst/export-network-travel-modes.html).
- [ArcPy Geometry.projectAs](https://doc.esri.com/en/arcgis-pro/latest/arcpy/classes/geometry.html): explicit geometry projection and transformation behavior.
- [ArcPy Geometry.intersect and touches](https://doc.esri.com/en/arcgis-pro/latest/arcpy/classes/geometry.html): topological geometry operations and boundary relationships.
- [ArcPy Polyline.queryPointAndDistance](https://doc.esri.com/en/arcgis-pro/latest/arcpy/classes/polyline.html): nearest point, along-line measure, distance, and side.
- [H3 Python API quick reference](https://github.com/uber/h3-py/blob/master/docs/api_quick.md) and [polygon tutorial](https://github.com/uber/h3-py/blob/master/docs/polygon_tutorial.ipynb): v4 polygon coverage modes, cell shapes, and lat/lng coordinate order.
