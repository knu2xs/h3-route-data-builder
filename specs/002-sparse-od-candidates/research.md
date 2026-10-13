# Research: Sparse OD Candidates

## Decision: Keep spatial scope operations in the ArcPy geometry boundary

- **Decision**: Use ArcPy for AOI expansion, H3 polygon/AOI intersection, and geodesic
  representative-point distances in Feature 001's fixed WGS 84 / EPSG:4326 geometry contract,
  measured in meters. Do not derive or configure a projected analysis CRS. Keep pair enumeration,
  key construction, input validation, and metrics in portable Python code.
- **Rationale**: Constitution Principle II reserves spatial geometry work for ArcPy and requires
  non-spatial planning to import and test without ArcPy. Feature 001 fixes processing geometry to
  WGS 84 and geodesic measurements to meters; using the same contract avoids inconsistent
  distances or an unauthorized CRS parameter.
- **Alternatives considered**: Use H3-only cell indexing for the exact AOI test, or use a
  third-party geometry library or derive a projected analysis CRS. These do not match Feature
  001's chosen geometry contract.

## Decision: Expand destination scope by conservative reach plus origin offset

- **Decision**: For the in-AOI origin representative set, calculate the greatest geodesic
  distance in meters from any representative to the nearest point on the AOI geometry, with zero
  for representatives inside the AOI. Geodesically expand the AOI by that maximum plus the
  cutoff-derived reach. Include a destination when its canonical H3 polygon intersects this
  expanded AOI.
- **Rationale**: A route from an origin representative to a destination representative that meets
  a distance cutoff cannot have a straight-line separation greater than that cutoff. For a time
  cutoff, the same guarantee requires a documented maximum permitted network speed or an
  equivalent proven bound. Accounting for the origin offset and using polygon intersection
  conservatively includes the H3 cell containing any qualifying destination representative.
- **Measurement pitfall**: A point-to-polygon distance operation must measure to the nearest
  polygon point, not its centroid. ArcPy `PointGeometry.angleAndDistanceTo` measures to a polygon
  centroid; it is not the required boundary distance. Use a documented ArcPy geodesic
  nearest-geometry measurement in meters and explicitly request geodesic AOI expansion.
- **Alternatives considered**: Test destination representative membership alone (rejected by
  clarification); use a fixed buffer unrelated to actual origin offsets (not reliably complete);
  search the entire network (unbounded); use a point-to-polygon centroid distance (not a bound on
  distance to the AOI geometry).

## ArcGIS Pro references

- [Buffer (Analysis Tools)](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/analysis/buffer.html):
  geodesic method for earth-surface buffering and linear distance conversion to meters.
- [PointGeometry](https://doc.esri.com/en/arcgis-pro/latest/arcpy/classes/pointgeometry.html):
  geodesic point distance returns meters; a polygon operand is measured to its centroid.
- [Generate Near Table (Analysis)](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/analysis/generate-near-table.html):
  geodesic nearest-feature distance for geographic input is reported in meters.

## Decision: Use a conservative straight-line lower bound only to prune

- **Decision**: Treat `network.prefilter_distance_error_bound_m` as an explicit finite,
  nonnegative upper bound on absolute representative-distance measurement error, covering
  coordinate precision, geodesic measurement, and unit conversion. The configured value is the
  caller's assertion that this bound is defensible; software validates its form, not its accuracy.
  Compute a conservative lower bound as
  `max(0, measured_distance_m - prefilter_distance_error_bound_m)` and prune only when that value
  is strictly greater than the cutoff-derived reach. If no defensible bound is supplied, retain
  the pair and report the fallback; do not invent a tolerance.
  Include the bound in candidate-policy provenance and the behavior fingerprint. Apply the
  configured cutoff only to the actual network result after solving.
- **Rationale**: A configured, auditable absolute-error bound converts the measured geodesic
  distance into a conservative lower bound when the caller can justify that bound. Retaining
  pairs when no bound is available preserves correctness without requiring an arbitrary default.
- **Alternatives considered**: Subtract an unconfigured hard-coded epsilon (untraceable and
  potentially unsafe); always prune using the raw measurement (does not account for error); or
  reject a build whenever no error bound is available (unnecessarily prevents a correct
  unpruned build).

## Decision: Keep actual-cost cutoff classification in the Feature 003 solve handoff

- **Decision**: Feature 002 supplies the configured cutoff, units, and expected logical keys to
  Feature 003. Feature 003 owns route solving and durable lifecycle; it must apply the cutoff to
  the actual solved network cost before validation, commit, or publication as a qualifying fact.
  A route result above cutoff is recorded as `cutoff-excluded`, not committed as a qualifying OD
  cost. Estimated and prefilter values are not eligible substitutes for solved network cost.
- **Rationale**: Keeps the boundary aligned with Feature 003's existing ownership of solve
  classification and ledger state while making cutoff enforcement an explicit acceptance point.
- **Alternatives considered**: Enforce cutoff during candidate planning before solving (would
  compare an estimate rather than actual cost); let downstream publication infer the cutoff
  (could commit invalid qualifying results).

## Decision: Separate logical pair identity from work-unit identity

- **Decision**: Identify a pair by the ordered composite `(origin_h3_id, destination_h3_id)`.
  Keep dataset fingerprint and origin/destination batch identity in Feature 003's work record,
  not in the logical pair key. Sort canonical H3 IDs before deterministic per-origin destination
  batching.
- **Rationale**: The ordered composite is collision-free as a logical identity, distinguishes
  reverse directions, and remains stable if the candidate scope or batch boundaries change.
  Feature 003 can therefore reconcile committed expected keys after AOI expansion.
- **Alternatives considered**: Sort endpoints as an unordered pair (loses direction); include
  batch number or dataset fingerprint in the pair key (makes the same route fact appear as a
  different logical pair after scope changes); hash without retaining the endpoint composite
  (unnecessary collision and audit concerns).

## Decision: Keep self-pairs out of route work

- **Decision**: Emit one resolved zero-cost self-pair for each origin cell. In surrounding mode,
  destination-only cells do not get self-pairs. Exclude all self-pairs from prefilter and network
  work counts.
- **Rationale**: Self-pairs express identity for the requested origin set and have known zero cost;
  a route solve would be redundant. This matches the clarified scope and preserves accurate work
  metrics.
- **Alternatives considered**: Solve self-pairs through Network Analyst (wasted work and possible
  inconsistent zero results); create self-pairs for surrounding-only destinations (outside the
  origin-to-destination request).

## Decision: Hand off only unsatisfied retained pairs to the resumable ledger

- **Decision**: Reconcile retained non-self logical keys with Feature 003. Reuse compatible
  committed facts, resume existing recoverable work, and create work only for absent or
  invalidated keys. Keep filtered and self-pair outcomes out of route-solve work while including
  them in candidate accounting.
- **Rationale**: Feature 003 defines durable states, leases, staging, and atomic commit. Reusing
  its logical-key reconciliation avoids a duplicate persistence model and supports restarts.
- **Alternatives considered**: A Feature 002-specific ledger or scheduling all candidates and
  filtering later (duplicates state ownership or schedules unnecessary work).

## Decision: Use existing resource-policy infrastructure and no new dependency

- **Decision**: Resolve batch and output limits through the project's resource-aware execution
  policy; persist resolved provenance with the run and resume using saved values. Add no package.
- **Rationale**: The constitution requires bounded candidate evaluation and reproducible resumed
  limits. `eligibility/limits.py` already implements explicit/inferred values and manifest
  restoration. Candidate batches can use that shared policy while Feature 003 owns durable work.
- **Alternatives considered**: Add a separate limit framework (duplicated policy); infer limits
  afresh on resume (non-reproducible); add geometry or ledger dependencies (not justified).
