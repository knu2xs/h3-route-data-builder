# Proposed Constitution Amendment: Builder Engine Policy

**Status**: Design proposal, not an enacted amendment.
**Current version**: 2.0.1
**Proposed version**: 3.0.0

## Rationale and Approval Boundary

Feature 007 explicitly broadens eligibility geometry from ArcPy-only execution to GeoAccessor
and DuckDB Spatial and standardizes persistent relational working databases on DuckDB.
This redefines a builder-specific principle, requiring a major version under current Governance.
Prepare and enact the amendment through a separate, explicit constitution-update workflow before
conflicting runtime work, including the pull request required by current Governance with rationale,
fresh-state cutover impact and dependent documentation. Local text preparation alone does not
satisfy the gate; record the amendment PR and enacted version before releasing it. This proposal
does not define additional approval rules. Do not weaken shared sparse/reproducibility/resumability
principles or claim solver approval. No PR creation is authorized merely by this planning artifact.

## Replacement Principle II: Builder Spatial and Network Boundary

Only the builder imports ArcPy. Within the builder, ArcPy and ArcGIS spatial dependencies MUST
be confined to spatial/network/geoprocessing boundaries and loaded only where needed.

- Small, safely memory-resident spatial tabular processing, including AOI, edge, H3 polygon and
  eligibility geometry, MUST use Pandas with the ArcGIS GeoAccessor and approved ArcGIS geometry
  capabilities.
- Larger or uncertain-size tabular processing MUST use bounded DuckDB operations; spatial
  operations MUST use its installed Spatial extension where equivalent capabilities exist.
- Unsupported or semantically non-equivalent spatial operations MUST be delegated explicitly
  to bounded GeoAccessor/ArcPy batches, with logged provenance and unchanged memory/correctness
  guarantees. If the capability or bound cannot be satisfied, fail explicitly.
- ArcPy remains the boundary for Network Analyst, network location and geoprocessing/source
  capabilities that require it. Network solving is not replaced by a geometry SQL engine.
- Direct GeoPandas, Shapely and pyproj application use and silent open-source geometry fallback
  are prohibited. This does not prohibit DuckDB Spatial's internal dependencies.
- H3 math, non-spatial eligibility/state rules, planning, ledger, manifest and non-spatial
  validation MUST remain importable/testable without ArcPy or ArcGIS spatial dependencies.

*Rationale:* standardize typed small/large spatial processing without changing network semantics,
exact identities or the portable non-spatial boundary.

## Principle VIII and Technology Constraints Additions

Retain current GeoParquet/PyArrow/DuckDB reader requirements and the GeoPandas prohibition.
Clarify that:

- Arrow/PyArrow remains approved for schemas, exact typed interchange, file I/O and metadata;
  plain control records do not need to become spatial DataFrames.
- Required H3 identities MUST retain exact validated integers and explicit 64-bit column types
  through spatial tables, database storage and publication; no float/text alias is allowed.
- Persistent relational working databases MUST be native on-disk DuckDB, not SQLite. Temporary
  DuckDB queries MAY be in memory. JSON manifests and immutable Parquet/GeoParquet artifacts
  remain approved and are not subject to forced database conversion.
- Only the coordinator owns authoritative read-write database access; workers never open it.
- Spatial extensions MUST be provisioned in environment setup, not downloaded during builds.
- Engine choices, resource budgets, relevant versions and delegated operations MUST be explicit,
  bounded and recorded; saved policy controls resume.

## Synchronization and Cutover Checklist for Implementation Planning

- Update `.specify/memory/constitution.md` Sync Impact Report, version and amendment date.
- Update canonical `AGENTS.md` spatial/DataFrame/SQL guidance, not manually maintained generated
  instruction copies; use existing regeneration support if available and report its absence.
- Check `.specify/templates/plan-template.md` and other templates for conflicting requirements;
  update only actual conflicts. Preserve the gate requiring constitution checks.
- Update current design/architecture and Features 001-006 engine descriptions with explicit
  supersession notes rather than erasing historical SQLite/ArcPy decisions.
- Update configuration/API/ArcGIS operator help and XML sidecars; verify help in Pro.
- Document required spatial dependency extra, ArcGIS environment matrix and offline extension setup.
- Require fresh DuckDB ledger and fresh working output where engine metadata is absent.
  Preserve legacy files/sidecars and old publications without migration or silent adoption.

Principle XVII's existing limit formulas remain unchanged; the new engine budget policy adds
controls alongside those formulas. All lifecycle, representative, worker and publication
guarantees remain in force.
