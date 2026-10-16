# Contract: Review Feature Class Export Interfaces

**Feature**: [spec.md](../spec.md) | **Data model**: [data-model.md](../data-model.md)

This feature exposes three interfaces: the ArcGIS Pro tool parameters, two package functions,
and an addition to the shared data contract document.

## 1. Tool parameters (Build H3 Geometry Eligibility)

Appended after the existing nine parameters. Existing indices 0–8 are unchanged (FR-003).

| Index | Name | Display name | Datatype | Type | Direction | Default |
|---|---|---|---|---|---|---|
| 9 | `export_review_feature_class` | Also Save Hexagons as Feature Class | `GPBoolean` | Optional | Input | `False` |
| 10 | `review_feature_class` | Output Hexagon Feature Class | `DEFeatureClass` | Optional | Output | none; disabled until index 9 is checked |

### Validation (`updateParameters` / `updateMessages`)

| Condition | Result |
|---|---|
| Index 9 unchecked | Index 10 disabled; no error even if empty |
| Index 9 checked, index 10 empty | Error on index 10: required when export is checked |
| Index 10 parent workspace is not a geodatabase | Error on index 10: choose a file, mobile, or enterprise geodatabase |
| Index 10 exists and `arcpy.env.overwriteOutput` is false | Error on index 10: output already exists |

### Execution (`execute`)

1. Run `run_geometry_eligibility` exactly as before (no new arguments).
2. If index 9 is checked, call `export_eligibility_review_feature_class(summary.run_directory,
   review_feature_class)` and log the returned count.
3. If step 1 raises, step 2 never runs.

## 2. Package API

### `h3_route_data_builder.eligibility.review` (ArcPy-free)

```python
@dataclass(frozen=True)
class ReviewCell:
    h3_id: int
    eligibility_status: str
    cell_geometry_wkb: bytes


def iter_review_cells(run_directory: str | os.PathLike[str]) -> Iterator[ReviewCell]:
    """Yield validated cells from a completed run in ascending h3_id order."""


def expected_review_cell_count(run_directory: str | os.PathLike[str]) -> int:
    """Return the completed run's manifest cell_result_count."""
```

**Raises `ValueError`** when: the manifest is missing or unreadable; `run_status` is not
`complete`; a listed part fails checksum/row-count/schema verification; an `h3_id` is not a valid
H3 cell or its resolution differs from `policy.h3_resolution`; `h3_id` order is not strictly
ascending; a required value is null or empty.

Behavior guarantees: reads only manifest-listed parts; holds at most one partition's rows in
memory; does not write to the run directory.

### `h3_route_data_builder.network.review_export` (ArcPy)

```python
def export_eligibility_review_feature_class(
    run_directory: str | os.PathLike[str],
    output_feature_class: str | os.PathLike[str],
) -> int:
    """Write a WGS 84 hexagon feature class for review; return the feature count."""
```

**Behavior**:

- Creates a Polygon feature class in WGS 84 with `h3_index` (`TEXT`, 20, `str(h3_id)`) and
  `eligibility_status` (`TEXT`, 32), then inserts one row per `ReviewCell` in stream order.
- Verifies the inserted count equals `expected_review_cell_count`.
- Logs start, target path, count, and completion; logs a warning when the count is zero.
- On any failure: deletes the target if it exists, logs the error, and re-raises.

## 3. Shared data contract addition

Add to `docsrc/mkdocs/design/03-data-contract.md`, without changing contract or schema versions:

```markdown
## Review artifacts (non-contract)

The builder can optionally write an eligibility review feature class of H3 hexagons for
interactive inspection in ArcGIS Pro.

- It is builder-local, optional, and never published, versioned, or fingerprinted.
- `h3_index` holds the same exact integer identity as contract `h3_id`, stored as exact decimal
  text because ArcGIS Big Integer fields are limited to 53 bits, too small for H3 indices. This
  text form is a review convenience, not a contract identity; `eligibility_status` is copied
  unchanged.
- Consumers, including `h3-route-solver`, MUST NOT read it as contract data.
- All contract Arrow/Parquet/JSON H3 identities remain non-null `uint64` integers.
```
