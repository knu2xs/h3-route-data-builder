# h3-route-data-builder Python Toolbox (`h3_route_data_builder.pyt`)

This is the documentation to be included if planning on packaging the `h3_route_data_builder.pyt`
toolbox using the `make pyt_pkg` command invoking the `./scripts/make_pyt_archive.pyt`. This script
packages the `h3_route_data_builder.pyt`, supporting Python package 
`./src/h3_route_data_builder` and any dependencies listed in `pyproject.toml`. This enables you to
distribute the Python toolbox for non-technical users with any custom libraries you are utilizing.

## Integer H3 output

New eligibility GeoParquet uses a required `uint64` `h3_id` column and eligibility schema
version 2. Representatives, geometry, toolbox parameters, and execution-limit defaults
are unchanged. Network Analyst uses opaque temporary labels rather than storing H3
identities as floating-point fields.

When upgrading from hexadecimal-index output, select a fresh eligibility output folder.
For downstream OD work, select a separate fresh format-2 ledger and rebuild; legacy
ledgers are rejected without migration or deletion. Do not rewrite historical publications.
New publication schemas are `2.0.0`; solver adoption of the shared integer contract is a
separate coordinated release gate.