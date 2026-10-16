# Quickstart: Validate the H3 Hexagon Review Export

**Feature**: [spec.md](./spec.md) | **Contract**: [contracts/review-feature-class.md](./contracts/review-feature-class.md)

## Prerequisites

- ArcGIS Pro 3.3 or later (the project requires Python 3.11+) with
  Network Analyst, and the project conda environment (`make env`).
- Run commands from the repository root with the environment activated.

## 1. ArcPy-free checks

```powershell
pytest testing/test_eligibility_review.py -v
```

Expected: passes without ArcPy. Covers manifest-listed part selection (stale parts ignored),
invalid or wrong-resolution H3 rejection, strictly ascending ordering across partitions, and
refusal of incomplete runs.

## 2. ArcPy export checks

```powershell
pytest testing/test_network_review_export.py -v
```

Expected: passes in the ArcGIS Pro environment; skips cleanly without ArcPy. Covers the feature
class schema (`h3_index` is Text 20 holding the decimal `h3_id`), WGS 84 spatial reference, row count equal to the
manifest, `h3_index`/`eligibility_status` parity with GeoParquet, zero-cell output, and cleanup
after an injected failure.

## 3. Toolbox and documentation checks

```powershell
pytest testing/test_h3_route_data_builder.py -v
```

Expected: the tool's parameter list ends with `export_review_feature_class` and
`review_feature_class`, and every parameter name appears in the XML sidecar help.

## 4. Full regression

```powershell
make test
```

Expected: all suites pass, including unchanged data contract schema tests (SC-005).

## 5. Manual validation in ArcGIS Pro

1. Open **Build H3 Geometry Eligibility**. Confirm the new checkbox is unchecked and the output
   feature class parameter is disabled.
2. Check the box with no path. Confirm a validation error. Choose a folder (shapefile) path.
   Confirm the geodatabase error.
3. Run with a small AOI and a file geodatabase target. Confirm the GeoParquet run completes, the
   feature class is added, and the message log reports the feature count.
4. Inspect fields: `h3_index` is Text (length 20) holding the exact decimal `h3_id`, and
   `eligibility_status` is Text (length 32). Symbolize by
   `eligibility_status` and confirm solvable and non-solvable cells appear.
5. Rerun unchecked on the same inputs. Confirm the run fingerprint and manifest are unchanged.
6. Open tool help and confirm the new parameter descriptions appear (Principle XVI).

## Requirement coverage

| Requirement | Validated by |
|---|---|
| FR-001–FR-003 | Step 3; manual 1–2 |
| FR-004–FR-010 | Steps 1–2; manual 3–4 |
| FR-011–FR-014 | Steps 1–2; manual 3, 5 |
| FR-015–FR-016 | Step 1 runs without ArcPy |
| FR-017–FR-019 | Steps 1–3 |
| FR-020–FR-022 | Step 3; manual 6; contract doc review |
| SC-001–SC-005 | Steps 2, 4; manual 3–5 |
