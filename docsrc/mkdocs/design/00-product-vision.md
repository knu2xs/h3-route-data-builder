# Product Vision

## Outcome

Create a sparse precomputed routing dataset from canonical-resolution H3 polygons intersecting a configured transportation network. Resolve arbitrary coordinates or H3 cells to nearby solvable cells at query time, then combine quantified endpoint stretch with a precomputed network OD result.

## Goals

- Default to H3 resolution 10 but keep resolution configurable.
- Mark a cell solvable only when its polygon intersects an eligible traversable edge.
- Solve OD pairs only between solvable cells.
- Support AOI-only and AOI-to-surrounding builds.
- Resume interrupted work and enlarge coverage without recomputing compatible rows.
- Resolve unsolved inputs with bounded H3 `k`, distance, or speed-and-time limits.
- Keep origin stretch, network solve, and destination stretch separate.
- Expose Python and MCP proximity operations without ArcPy.

## Non-goals

Exact off-network routing, route geometry, live traffic, and treating H3 hop distance as exact physical distance are outside the first release.
