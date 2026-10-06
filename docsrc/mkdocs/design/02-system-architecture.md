# System Architecture

```text
AOI + eligible transportation edges
  -> intersecting canonical H3 cells
  -> deterministic on-edge representatives
  -> sparse OD candidate batches
  -> ArcPy Network Analyst solve
  -> partitioned Parquet/GeoParquet

coordinate or H3
  -> canonical H3
  -> bounded gridDisk/grid-ring search
  -> solvable endpoint candidate(s)
  -> precomputed OD lookup
  -> separate stretch + network + combined metrics
```

## Builder

The ArcPy builder contains AOI normalization, traversable-edge extraction, solvable-cell generation, representative selection, candidate planning, work ledger, OD workers, publishing, and verification.

For each intersecting cell, choose a deterministic point on an eligible intersecting edge, initially the eligible point nearest the cell centroid with source-ID/OID/measure tie-breaking. This point is the network representative. Its network-location snap should be zero within numeric tolerance.

## Solver

The ArcPy-free solver contains a manifest catalog, solved-cell membership index, input normalizer, bounded H3 stretch resolver, endpoint-selection policy, partition reader, query service, and MCP adapter.

## Stretch budgets

Support `max_k`, `max_stretch_distance_m`, and `max_stretch_time_s` with `stretch_speed_mps`. Convert distance/time to an initial `k` estimate, but verify candidates using the configured stretch metric. Apply the strictest supplied bound.

## Concurrency

Use a serial reference path. Optional process workers get isolated scratch workspaces. The coordinator owns leases and commits. Serialize ArcPy solves if licensing or locking makes concurrent solves unsafe.
