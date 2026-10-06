---
applyTo: "**/*.pyt,arcgis/**/*.py,src/**/*.py,scripts/**/*.py"
---

<!-- Generated from AGENTS.md by post_gen_project.py — do not edit directly. -->

- Prefer `arcpy.da.UpdateCursor` over older cursor methods for better performance
- Use generator expressions to feed values into cursors when possible
- Always clean up cursors using `with` statements, `del` statements, or as context managers
- When calling arcpy tools, use the convention `arcpy.toolbox.Toolname` instead of 
  `arcpy.Toolname_toolbox`, and use named parameters for clarity and forward compatibility

#### 7.3 Intermediate Data Management

**For small datasets (< tens of thousands of features)**:

- Use the `memory` workspace for intermediate outputs: `memory/datasetname`
- Provides fastest performance for small to moderate datasets
- No cleanup required as data is automatically released

**For large datasets (≥ tens of thousands of features)**:

- Use the `@with_temp_fgdb` decorator from `h3_route_data_builder.utils` —
  implemented in `src/h3_route_data_builder/utils/_data.py` and included by default
  in generated projects
- Automatically sets `arcpy.env.workspace` to a temporary file geodatabase for the duration of
  the function, then deletes all intermediate data and the workspace on exit (even on error)
- Prevents memory issues with large intermediate datasets

```python
from h3_route_data_builder.utils import with_temp_fgdb
from pathlib import Path

@with_temp_fgdb
def process_large_dataset(
    input_fc: str,
    clip_boundary: str,
    output_fc: str,
    temp_fgdb: str = None,
) -> str:
    """
    Process a large dataset using a temporary file geodatabase.

    Args:
        input_fc: Path to input feature class.
        clip_boundary: Path to feature class used to clip the buffered output.
        output_fc: Path to output feature class.
        temp_fgdb: Temporary file geodatabase path (injected by decorator).

    Returns:
        str: Path to the output feature class.
    """
    # Use temp_fgdb for intermediate outputs
    intermediate_fc = str(Path(temp_fgdb) / "intermediate")
    arcpy.analysis.Buffer(
        in_features=input_fc,
        out_feature_class=intermediate_fc,
        buffer_distance_or_field="100 METERS"
    )
    arcpy.analysis.Clip(
        in_features=intermediate_fc,
        clip_features=clip_boundary,
        out_feature_class=output_fc
    )
    return output_fc
```
