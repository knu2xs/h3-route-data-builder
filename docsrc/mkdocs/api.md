---
title: Python API
---

::: h3_route_data_builder

## Integer H3 identities

H3-bearing APIs accept exact integer cell IDs, not hexadecimal or decimal strings.
Use H3's native integer API at input creation:

```python
from h3.api import basic_int as h3
from h3_route_data_builder.eligibility.cells import canonical_h3_ids

cell_id = h3.latlng_to_cell(40.7484, -73.9857, 9)
cells = canonical_h3_ids([cell_id, cell_id])
assert cells == [cell_id]
```

Eligibility models expose `h3_id`; directed pairs expose `origin_h3_id` and
`destination_h3_id`. Keys are ordered integer pairs. New published H3 columns are required
`uint64` fields under schema `2.0.0`. JSON readers must preserve integer precision above `2^53`.
See the [proposed shared contract](design/03-data-contract.md) for consumer adoption status.

## Module `h3_route_data_builder.utils`

::: h3_route_data_builder.utils

## Module `h3_route_data_builder.eligibility.review`

::: h3_route_data_builder.eligibility.review

## Module `h3_route_data_builder.network.review_export`

::: h3_route_data_builder.network.review_export
