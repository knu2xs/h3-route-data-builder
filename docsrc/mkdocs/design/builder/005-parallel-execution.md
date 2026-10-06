# Feature 005: Parallel Execution

- Maintain a one-process reference implementation.
- Use processes, not shared-thread assumptions, for ArcPy solve workers.
- Give every worker a unique scratch directory and geodatabase.
- Never allow concurrent writes to one final partition.
- Let the coordinator own leases and publication.
- Run a small capability probe against the actual network/license configuration.
- Fall back to serialized solving on lock, license, initialization, or stability problems.
- Parallelize non-ArcPy preparation and validation where safe.

Parallel and serial fixture outputs must be logically identical.
