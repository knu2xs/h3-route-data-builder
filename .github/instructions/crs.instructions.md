---
applyTo: "**/*.py,**/*.pyt"
---

<!-- Generated from AGENTS.md by post_gen_project.py — do not edit directly. -->

Spatial bugs caused by mismatched or assumed CRS are among the most common — and most expensive
— errors in spatial workflows. Treat CRS as a first-class concern.

- **Never hardcode WKIDs / EPSG codes** in code. Define them in `config.yml` (e.g.
  `spatial.crs_working`, `spatial.crs_storage`, `spatial.crs_display`) and read via
  `config.spatial.crs_working`.
- **Validate CRS on every input** at the start of any function that consumes spatial data.
  If the input lacks a CRS, raise rather than guessing.
- **Reproject explicitly**, never implicitly. Document the target CRS in the function
  docstring and log the source → target transformation.
- **Project before measuring**. Area, length, and distance calculations must be performed
  in a projected CRS appropriate for the area of interest, not in geographic coordinates
  (e.g. WGS 84 / EPSG:4326).
- **GeoPandas**: use `gdf.to_crs(epsg=...)` and check `gdf.crs is not None` before any
  geometric operation. Do not use `gdf.set_crs(...)` to "fix" data with an unknown CRS.
- **ArcPy**: use `arcpy.management.Project` (not `Define Projection`) to actually transform
  coordinates. `Define Projection` only updates metadata and silently corrupts data when
  misused.
- **DuckDB**: use `ST_Transform(geometry, target_srid)` to reproject geometries to the CRS 
  defined in the configuration in SQL queries.
