# Roadmap

1. **Geometry spike:** define eligible edges, intersection semantics, deterministic representative, measured sparsity, H3 distance conversion, and pentagon behavior.
2. **Sparse builder slice:** AOI to edges to intersecting cells to representatives to serial OD to one partition.
3. **Resume/expand:** ledger, leases, reconciliation, fingerprints, and AOI enlargement.
4. **Parallel publication:** isolated workers, capability probe, fallback, compaction, metadata, and verification.
5. **Stretch resolver:** bounded H3 expansion, distance/time-to-`k`, ties, and provenance.
6. **Sparse API:** OD, nearest, reachable, and matrix with separate components.
7. **MCP:** strict tools, limits, packaging, and contract tests.

## `/speckit.clarify`

Resolve edge eligibility; whether boundary touch counts; representative selection; default endpoint-selection policy; approximate versus exact centroid distance; access speed; per-endpoint versus combined stretch limits; network-only versus combined cutoff semantics; maximum `k`/candidate count; and whether reachable output may expand from solvable cells to nearby unsolved cells.
