# Test Strategy

## Unit

Test H3 forms, safe grid traversal, average-edge conversion, time/distance-to-`k` rounding, membership lookup, tie-breaking, component formulas, manifests, and fingerprints.

## Builder integration

Use a synthetic network with crossing, nearby-but-not-intersecting, restricted, one-way, and disconnected edges. Prove only intersecting eligible cells enter OD work and representatives lie on eligible edges.

## Solver

Test already-solvable cells; candidates at several rings; ties; missing candidates; `k`, distance, and speed/time cutoffs; approximate versus exact centroid distance; pentagon behavior; bounded minimum-combined-cost selection; and separated response metrics.

## Resilience/interoperability

Terminate each solve/commit stage and reconcile after restart. Validate Parquet/GeoParquet with PyArrow, DuckDB, and GeoPandas where applicable.
