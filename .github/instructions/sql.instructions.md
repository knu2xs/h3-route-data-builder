---
applyTo: "src/**/*.py,scripts/**/*.py,src/**/sql/*.sql"
---

<!-- Generated from AGENTS.md by post_gen_project.py — do not edit directly. -->

Externalise non-trivial SQL into discrete `.sql` files under
`src/h3_route_data_builder/sql/`. This is a widely adopted best practice because it:

- Enables full SQL syntax highlighting, formatting, and linting in VS Code (e.g. the
  *SQLTools* and *SQLFluff* extensions) — features that do not work on SQL embedded in Python
  string literals.
- Produces clean, reviewable diffs for long queries.
- Eliminates Python-string escaping issues (quotes, backslashes, f-string `{}` collisions).
- Encourages parameterized queries (`$name`, `?`) over string interpolation, sidestepping
  SQL injection.
- Allows the same query to be reused by Python, notebooks, dbt, or a CLI.

**When to inline vs. externalise:**

- **Inline**: short ad-hoc queries (≤ ~10 lines) with no user-supplied input.
- **Externalise**: anything multi-statement, multi-CTE, longer than ~10 lines, parameterized,
  or reused in more than one place.

**File layout:**

```
src/h3_route_data_builder/
    sql/
        __init__.py              # exposes load_sql() helper
        h3_aggregate.sql
        nearest_poi.sql
        load_parquet_partitioned.sql
```

**Naming:** `snake_case.sql`, named after the operation (`build_index.sql`,
`spatial_join_blocks.sql`), not the table.

**Loading and executing** (canonical pattern — `load_sql()` is shipped with the package):

```python
import duckdb
from h3_route_data_builder.sql import load_sql

con = duckdb.connect()
result = con.execute(
    load_sql("nearest_poi"),
    {"max_distance_m": 1500, "category": "grocery"},
).fetch_df()
```

**Always parameterise**. Use DuckDB's named-parameter form (`$max_distance_m`) and pass a
dict to `execute()`. Never `f"... WHERE category = '{category}'"`-style interpolation, even
for "internal" inputs.

**For values that cannot be bound** (table or column names, file paths in `read_parquet(...)`),
validate them against an allow-list before substituting via Python `str.format` or Jinja.

**Configuration over hardcoding**: paths to Parquet datasets, working CRS WKIDs, and
H3 resolutions belong in `config.yml` (see §5) and should be passed in as bind parameters,
not baked into the `.sql` file.
