# Shared Constitution

1. **Explicit semantics:** eligibility, travel mode, H3 resolution, network cutoff, stretch cutoff, distance conversion, speed, units, and tie-breaking are configuration.
2. **ArcPy isolation:** only the builder imports ArcPy.
3. **Sparse correctness:** no nonintersecting cell may enter OD work.
4. **Immutable reproducibility:** published data is versioned and fingerprinted from network, travel mode, restrictions, policy, schema, and software versions.
5. **Idempotent resumability:** deterministic work keys, staging, validation, atomic commit, and reconciliation are mandatory.
6. **Approximation transparency:** H3-derived distance and speed-derived time are always labeled estimates.
7. **Bounded execution:** all ring expansion, candidate evaluation, and API output have limits.
8. **Interoperability:** published spatial files validate against the selected GeoParquet specification.
9. **Observable operation:** structured logs and durable states reconcile all work.
10. **Testable contracts:** every requirement has acceptance coverage.
