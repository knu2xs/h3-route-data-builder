# Shared Data Contract

## Manifest

Store contract/dataset versions, H3 resolution and library version, H3 average edge length, center-spacing factor, CRS, network/travel-mode fingerprints, solvable-cell policy, representative policy, OD cutoff policy, default stretch policy, GeoParquet version, partition scheme, and statistics.

## Solvable cells

Required fields include `h3_id_hex`, optional safe `h3_id_uint64`, resolution, cell geometry, centroid geometry, network representative geometry, intersecting-edge count, network source/OID/percent-along/side fields, representative snap distance, eligibility status, and build fingerprint.

Only `eligibility_status=solvable` rows may participate in OD work.

## OD facts

Store origin/destination H3, travel mode, network distance, network time, representative snap distances, solve status, work-unit ID, and build fingerprint. Do not persist query-specific stretch as network cost.

## Query metrics

Return requested and resolved endpoint cells; endpoint `grid_k`; H3-derived stretch distance; optional exact centroid great-circle distance; optional inferred stretch time; network distance/time; combined distance/time; and all policy/provenance fields.

```text
estimated_stretch_distance_m = grid_k * center_spacing_factor * average_edge_length_m
combined_distance_m = origin_stretch_distance_m + network_distance_m + destination_stretch_distance_m
combined_time_s = origin_stretch_time_s + network_time_s + destination_stretch_time_s
```

Use `sqrt(3)` as the default regular-hex center-spacing factor, label the result approximate, and do not use it as a guaranteed maximum without a conservative cell-extent allowance. Stretch time is null without an explicit speed policy.

Statuses include `invalid_input`, `no_solvable_cell_within_cutoff`, `not_built`, `unreachable`, `outside_network_cutoff`, and `dataset_error`.
