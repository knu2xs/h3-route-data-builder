# Shared Data Contract

!!! warning "Version 2 coordinated adoption pending"
    The builder implements the proposed integer-index contract below. Adoption by `h3-route-solver`
    and execution of the same conformance fixture in that project remain release gates.
    Builder tests alone do not establish solver compatibility. Historical version 1 publications
    retain their original hexadecimal schemas and must not be relabeled or rewritten.

## H3 identity

- Use exact Python integers for all H3 identities, including directed `(origin, destination)` keys.
- Require valid H3 cells at the configured resolution in the unsigned 64-bit domain. Reject
  strings (hexadecimal or decimal), booleans, floats, nulls, and invalid cell bit patterns.
- Order and deduplicate identities numerically. Direction remains significant; self-pairs retain zero cost.
- Arrow/Parquet H3 columns are non-null `uint64`. There are no `_hex` or optional `_uint64` aliases.
- JSON H3 values and collections are integer values and numeric arrays. Encode cell-indexed maps
  as sorted records containing an integer ID, not JSON object keys. Consumers must parse numbers
  exactly above `2^53`; JavaScript `Number` is not a lossless H3 representation.
- Integer storage avoids redundant textual identities and is motivated by efficiency, including
  edge devices such as phones. No performance or memory reduction is promised without measurement.

## Manifest

Store contract/dataset versions, H3 resolution and library version, H3 average edge length, center-spacing factor, CRS, network/travel-mode fingerprints, solvable-cell policy, representative policy, OD cutoff policy, default stretch policy, GeoParquet version, partition scheme, and statistics.

The proposed shared contract and dataset/cell/fact schemas are `2.0.0`; GeoParquet remains `1.1.0`.
Partition manifests contain numeric `origin_ids` arrays. An `origin_h3_id=<decimal>` directory
is only a location label: typed columns and manifest arrays, not path parsing or Hive inference,
establish cell identity.

## Solvable cells

Required fields include non-null `uint64` `h3_id`, resolution, cell geometry, centroid geometry,
network representative geometry, intersecting-edge count, network source/OID/percent-along/side
fields, representative snap distance, eligibility status, and build fingerprint.

Only `eligibility_status=solvable` rows may participate in OD work.

## OD facts

Store origin/destination H3, travel mode, network distance, network time, representative snap distances, solve status, work-unit ID, and build fingerprint. Do not persist query-specific stretch as network cost.

Endpoints are non-null `uint64` `origin_h3_id` and `destination_h3_id`. Unlocated, unreachable,
and cutoff-excluded outcomes remain durable diagnostic evidence but are not route facts.
This representation cutover does not change eligibility, candidate selection, costs, cutoff policy,
geometry, or worker policy.

## Query metrics

Return requested and resolved endpoint cells; endpoint `grid_k`; H3-derived stretch distance; optional exact centroid great-circle distance; optional inferred stretch time; network distance/time; combined distance/time; and all policy/provenance fields.

```text
estimated_stretch_distance_m = grid_k * center_spacing_factor * average_edge_length_m
combined_distance_m = origin_stretch_distance_m + network_distance_m + destination_stretch_distance_m
combined_time_s = origin_stretch_time_s + network_time_s + destination_stretch_time_s
```

Use `sqrt(3)` as the default regular-hex center-spacing factor, label the result approximate, and do not use it as a guaranteed maximum without a conservative cell-extent allowance. Stretch time is null without an explicit speed policy.

Statuses include `invalid_input`, `no_solvable_cell_within_cutoff`, `not_built`, `unreachable`, `outside_network_cutoff`, and `dataset_error`.
