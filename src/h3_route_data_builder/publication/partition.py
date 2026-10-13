"""Origin-based fact partitioning and pruned reads."""

from collections.abc import Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from h3_route_data_builder.publication.models import PublishedPart
from h3_route_data_builder.publication.schema import OD_FACTS_SCHEMA


def read_origin_facts(
    parts: Sequence[PublishedPart], origin_h3_id_hex: str
) -> tuple[pa.Table, int]:
    """Read only fact parts whose recorded origin metadata includes the selected origin."""
    matching = [part for part in parts if origin_h3_id_hex in part.origin_ids]
    tables: list[pa.Table] = []
    for part in matching:
        table = pq.ParquetFile(part.path).read()
        matching_indices = [
            index
            for index, value in enumerate(table.column("origin_h3_id_hex").to_pylist())
            if value == origin_h3_id_hex
        ]
        tables.append(table.take(pa.array(matching_indices, type=pa.int64())))
    if tables:
        selected = pa.concat_tables(tables)
    else:
        selected = pa.Table.from_pylist([], schema=OD_FACTS_SCHEMA)
    return selected, len(matching)
