"""Fail-closed network-edge eligibility from ArcPy evaluator metadata."""

import ast
import json
import re
from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import arcpy

from h3_route_data_builder.utils import get_logger

logger = get_logger(__name__, level="DEBUG", add_stream_handler=False)

_ALONG: str = "AlongDigitizedDirection"
_AGAINST: str = "AgainstDigitizedDirection"
_DIRECTIONS: tuple[str, str] = (_ALONG, _AGAINST)
_FIELD_TOKEN = re.compile(r"!([A-Za-z_][A-Za-z0-9_]*)!")
_PROHIBITED_USAGE: set[int | str] = {-1, "-1", "PROHIBITED"}
_NONBLOCKING_USAGE: set[int | str] = {
    2,
    5,
    "2",
    "5",
    "AVOID",
    "AVOID_MEDIUM",
    "AVOID_HIGH",
}


@dataclass(frozen=True)
class EdgeEvaluator:
    """One source- and direction-specific network attribute evaluator."""

    source_name: str
    edge_direction: str | None
    evaluator_type: str
    expression: str


@dataclass(frozen=True)
class NetworkAttributeDefinition:
    """Network attribute metadata exposed by ArcPy Describe."""

    name: str
    usage_type: str
    evaluators: tuple[EdgeEvaluator, ...]
    default_edge_evaluator_type: str = "Constant"
    default_edge_data: Any = False


@dataclass(frozen=True)
class EdgeEligibilityDecision:
    """Allowed edge directions and auditable eligibility result."""

    eligibility_status: str
    allowed_directions: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class NetworkEdgeSource:
    """Resolved feature source referenced by a network dataset."""

    name: str
    source_id: int
    feature_class_path: str


@dataclass(frozen=True)
class NetworkDatasetMetadata:
    """Read-only network metadata needed for AOI-scoped edge evaluation."""

    network_path: str
    edge_sources: tuple[NetworkEdgeSource, ...]
    attributes: dict[str, NetworkAttributeDefinition]
    travel_modes: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class NetworkEdgeRecord:
    """One AOI-intersecting edge with its eligibility evidence."""

    source_id: int
    source_oid: int
    source_name: str
    geometry_working: arcpy.Geometry
    decision: EdgeEligibilityDecision


def load_network_metadata(network_dataset_path: str) -> NetworkDatasetMetadata:
    """Read edge sources, network evaluators, and travel modes from a network dataset.

    Args:
        network_dataset_path: ArcPy-resolvable network dataset path.

    Returns:
        Read-only source, attribute evaluator, and travel mode metadata.

    Raises:
        ValueError: If the dataset is unavailable or an edge source cannot be resolved.
        RuntimeError: If ArcPy cannot describe the network or its travel modes.
    """
    if not arcpy.Exists(network_dataset_path):
        raise ValueError(
            f"ArcPy cannot resolve network dataset: {network_dataset_path}"
        )
    try:
        description = arcpy.Describe(network_dataset_path)
        edge_sources: list[NetworkEdgeSource] = []
        source_directory = Path(description.catalogPath).parent
        for edge_source in description.edgeSources:
            source_path = source_directory / edge_source.name
            if not arcpy.Exists(str(source_path)):
                message = f"Network edge source cannot be resolved: {source_path}"
                logger.error(message)
                raise ValueError(message)
            edge_sources.append(
                NetworkEdgeSource(
                    name=edge_source.name,
                    source_id=int(edge_source.sourceID),
                    feature_class_path=str(source_path),
                )
            )

        attributes: dict[str, NetworkAttributeDefinition] = {}
        for attribute in description.attributes:
            evaluators = tuple(
                EdgeEvaluator(
                    source_name=str(getattr(attribute, f"sourceName{index}")),
                    edge_direction=getattr(attribute, f"edgeDirection{index}"),
                    evaluator_type=str(getattr(attribute, f"evaluatorType{index}")),
                    expression=str(getattr(attribute, f"data{index}")),
                )
                for index in range(int(attribute.evaluatorCount))
            )
            attributes[attribute.name] = NetworkAttributeDefinition(
                name=attribute.name,
                usage_type=str(attribute.usageType),
                evaluators=evaluators,
                default_edge_evaluator_type=str(attribute.defaultEdgeEvaluatorType),
                default_edge_data=attribute.defaultEdgeData,
            )

        travel_modes = {
            name: json.loads(str(mode))
            for name, mode in arcpy.na.GetTravelModes(network_dataset_path).items()
        }
    except ValueError:
        raise
    except Exception as exc:
        message = f"Could not inspect network dataset '{network_dataset_path}': {exc}"
        logger.error(message)
        raise RuntimeError(message) from exc

    logger.info(
        "Loaded network metadata from %s: %s edge source(s), %s network attribute(s), %s travel mode(s)",
        network_dataset_path,
        len(edge_sources),
        len(attributes),
        len(travel_modes),
    )
    return NetworkDatasetMetadata(
        network_path=network_dataset_path,
        edge_sources=tuple(edge_sources),
        attributes=attributes,
        travel_modes=travel_modes,
    )


def required_edge_fields(
    edge_source_name: str,
    network_attributes: dict[str, NetworkAttributeDefinition],
    travel_mode: dict[str, Any],
) -> list[str]:
    """List source fields referenced by direction and prohibited-edge evaluators.

    Args:
        edge_source_name: Edge feature source to inspect.
        network_attributes: ArcPy network attribute definitions.
        travel_mode: Parsed travel mode JSON.

    Returns:
        Case-insensitively deduplicated field names in deterministic order.
    """
    restriction_names = travel_mode.get("restrictionAttributeNames", [])
    usage = _restriction_usage(travel_mode) or {}
    relevant_attributes = [network_attributes.get("Travel Direction")]
    for restriction_name in restriction_names:
        if usage.get(restriction_name) in _PROHIBITED_USAGE:
            relevant_attributes.append(network_attributes.get(restriction_name))

    fields: dict[str, str] = {}
    for attribute in relevant_attributes:
        if attribute is None:
            continue
        for evaluator in attribute.evaluators:
            if (
                evaluator.source_name != edge_source_name
                or evaluator.evaluator_type.casefold() != "field"
            ):
                continue
            for match in _FIELD_TOKEN.finditer(evaluator.expression):
                fields.setdefault(match.group(1).casefold(), match.group(1))
    return sorted(fields.values(), key=str.casefold)


def iter_network_edges(
    network_dataset_path: str,
    travel_mode_name: str,
    spatial_filter: arcpy.Geometry,
    working_spatial_reference: arcpy.SpatialReference,
    datum_transformation: str | None = None,
) -> Iterator[NetworkEdgeRecord]:
    """Yield AOI-intersecting edge features with fail-closed travel eligibility.

    The SearchCursor uses the caller's projected AOI as a spatial filter and projects returned
    edge shapes into the same working CRS. It reads only the fields referenced by supported
    network evaluator metadata, plus the source OID and geometry.

    Args:
        network_dataset_path: ArcPy-resolvable network dataset path.
        travel_mode_name: Configured travel mode name.
        spatial_filter: Valid AOI geometry in the working projected CRS.
        working_spatial_reference: Configured projected CRS for returned geometries.
        datum_transformation: Explicit ArcGIS transformation when required.

    Yields:
        Edge records intersecting the AOI with eligible, restricted, or undetermined status.

    Raises:
        ValueError: If the spatial filter is invalid or the travel mode is unavailable.
        RuntimeError: If an edge-source cursor cannot be read.
    """
    if spatial_filter is None or spatial_filter.type.casefold() != "polygon":
        raise ValueError("spatial_filter must be a non-empty AOI polygon")
    if spatial_filter.pointCount == 0:
        raise ValueError("spatial_filter must be a non-empty AOI polygon")
    if spatial_filter.spatialReference != working_spatial_reference:
        raise ValueError(
            "spatial_filter must already use the working spatial reference"
        )
    if working_spatial_reference.type != "Projected":
        raise ValueError("working_spatial_reference must be projected")

    metadata = load_network_metadata(network_dataset_path)
    travel_mode = metadata.travel_modes.get(travel_mode_name)
    if travel_mode is None:
        raise ValueError(
            f"Unknown travel mode '{travel_mode_name}' for network dataset"
        )

    for source in metadata.edge_sources:
        field_names = required_edge_fields(
            source.name, metadata.attributes, travel_mode
        )
        cursor_fields = ["OID@", "SHAPE@", *field_names]
        try:
            with arcpy.da.SearchCursor(
                in_table=source.feature_class_path,
                field_names=cursor_fields,
                spatial_reference=working_spatial_reference,
                datum_transformation=datum_transformation,
                spatial_filter=spatial_filter,
                spatial_relationship="INTERSECTS",
            ) as cursor:
                for row in cursor:
                    edge_fields = dict(zip(field_names, row[2:]))
                    decision = classify_edge_directions(
                        source.name,
                        edge_fields,
                        metadata.attributes,
                        travel_mode,
                    )
                    yield NetworkEdgeRecord(
                        source_id=source.source_id,
                        source_oid=int(row[0]),
                        source_name=source.name,
                        geometry_working=row[1],
                        decision=decision,
                    )
        except arcpy.ExecuteError as exc:
            message = f"Could not read edge source '{source.name}' in '{network_dataset_path}': {arcpy.GetMessages(2)}"
            logger.error(message)
            raise RuntimeError(message) from exc


def evaluate_field_expression(expression: str, fields: dict[str, Any]) -> bool:
    """Evaluate the supported safe subset of ArcPy Field evaluator expressions.

    The parser supports field tokens, primitive constants, equality comparisons, and
    boolean ``and``, ``or``, and ``not``. It never executes arbitrary Python code.

    Args:
        expression: ArcPy Field evaluator expression such as ``!FT_ALLOWED! == 'Y'``.
        fields: Source feature attributes keyed by field name.

    Returns:
        Boolean evaluator result.

    Raises:
        ValueError: If a field is missing or the expression uses unsupported syntax.
    """
    field_values: dict[str, Any] = {}

    def replace_field(match: re.Match[str]) -> str:
        field_name = match.group(1)
        normalized_fields = {name.casefold(): value for name, value in fields.items()}
        if field_name.casefold() not in normalized_fields:
            raise ValueError(f"Missing evaluator field: {field_name}")
        variable_name = f"field_{len(field_values)}"
        field_values[variable_name] = normalized_fields[field_name.casefold()]
        return variable_name

    translated = _FIELD_TOKEN.sub(replace_field, expression)
    try:
        parsed = ast.parse(translated, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Malformed evaluator expression: {expression}") from exc
    return bool(_evaluate_node(parsed.body, field_values))


def _evaluate_node(node: ast.AST, fields: dict[str, Any]) -> Any:
    """Evaluate one allowlisted expression node without Python ``eval``."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in fields:
        return fields[node.id]
    if isinstance(node, ast.BoolOp):
        values = [_evaluate_node(value, fields) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _evaluate_node(node.operand, fields)
    if isinstance(node, ast.Compare):
        left = _evaluate_node(node.left, fields)
        for operator, comparator in zip(node.ops, node.comparators):
            right = _evaluate_node(comparator, fields)
            if isinstance(operator, ast.Eq):
                matched = left == right
            elif isinstance(operator, ast.NotEq):
                matched = left != right
            else:
                raise ValueError("Unsupported comparison in evaluator expression")
            if not matched:
                return False
            left = right
        return True
    raise ValueError(f"Unsupported evaluator syntax: {type(node).__name__}")


def classify_edge_directions(
    edge_source_name: str,
    fields: dict[str, Any],
    network_attributes: dict[str, NetworkAttributeDefinition],
    travel_mode: dict[str, Any],
) -> EdgeEligibilityDecision:
    """Determine which digitized edge directions remain traversable.

    Only explicit ``Travel Direction`` metadata and prohibited active edge-source
    restrictions can block a direction. Avoidance costs do not make an edge
    non-traversable. Turn-source restrictions are transition constraints, not
    edge-wide prohibitions. Unsupported expressions fail closed per direction.

    Args:
        edge_source_name: Name of the network edge source for this feature.
        fields: Edge attributes keyed by source field name.
        network_attributes: Read-only metadata from the network dataset.
        travel_mode: Parsed Network Analyst travel mode JSON.

    Returns:
        Eligibility status, allowed directions, and decision reason.
    """
    direction_attribute = network_attributes.get("Travel Direction")
    if (
        direction_attribute is None
        or direction_attribute.usage_type.casefold() != "descriptor"
    ):
        return EdgeEligibilityDecision(
            "undetermined", (), "Travel Direction attribute is unavailable"
        )

    restrictions = travel_mode.get("restrictionAttributeNames")
    if not isinstance(restrictions, list):
        return EdgeEligibilityDecision(
            "undetermined", (), "Travel mode restriction list is unavailable"
        )
    restriction_usage = _restriction_usage(travel_mode)
    if restriction_usage is None:
        return EdgeEligibilityDecision(
            "undetermined", (), "Travel mode restriction usage is unavailable"
        )

    allowed_directions: list[str] = []
    indeterminate_reasons: list[str] = []
    for direction in _DIRECTIONS:
        direction_allowed, reason = _evaluate_attribute_direction(
            direction_attribute, edge_source_name, direction, fields
        )
        if reason is not None:
            indeterminate_reasons.append(reason)
            continue
        if not direction_allowed:
            continue

        prohibited = False
        direction_indeterminate = False
        for restriction_name in restrictions:
            usage = restriction_usage.get(restriction_name)
            if usage in _PROHIBITED_USAGE:
                attribute = network_attributes.get(restriction_name)
                if attribute is None:
                    indeterminate_reasons.append(
                        f"Active prohibited restriction metadata is missing: {restriction_name}"
                    )
                    direction_indeterminate = True
                    break
                restricted, restriction_reason = _evaluate_attribute_direction(
                    attribute, edge_source_name, direction, fields
                )
                if restriction_reason is not None:
                    indeterminate_reasons.append(restriction_reason)
                    direction_indeterminate = True
                    break
                if restricted:
                    prohibited = True
                    break
            elif usage not in _NONBLOCKING_USAGE:
                indeterminate_reasons.append(
                    f"Unsupported restriction usage for {restriction_name}: {usage!r}"
                )
                direction_indeterminate = True
                break

        if not prohibited and not direction_indeterminate:
            allowed_directions.append(direction)

    if indeterminate_reasons:
        return EdgeEligibilityDecision(
            "undetermined", (), "; ".join(sorted(set(indeterminate_reasons)))
        )
    if allowed_directions:
        reason = "eligible in at least one permitted travel direction"
        return EdgeEligibilityDecision("eligible", tuple(allowed_directions), reason)
    return EdgeEligibilityDecision(
        "restricted", (), "all travel directions are prohibited"
    )


def _restriction_usage(travel_mode: dict[str, Any]) -> dict[str, Any] | None:
    """Read restriction-usage parameters by attribute name."""
    parameter_values = travel_mode.get("attributeParameterValues")
    if not isinstance(parameter_values, list):
        return None
    usage: dict[str, Any] = {}
    for parameter in parameter_values:
        if not isinstance(parameter, dict):
            continue
        if parameter.get("parameterName") == "Restriction Usage":
            attribute_name = parameter.get("attributeName")
            if isinstance(attribute_name, str):
                usage[attribute_name] = parameter.get("value")
    return usage


def _evaluate_attribute_direction(
    attribute: NetworkAttributeDefinition,
    edge_source_name: str,
    direction: str,
    fields: dict[str, Any],
) -> tuple[bool, str | None]:
    """Evaluate source-specific metadata for one direction or return an error."""
    evaluators = [
        evaluator
        for evaluator in attribute.evaluators
        if evaluator.source_name == edge_source_name
        and evaluator.edge_direction == direction
    ]
    if not evaluators:
        evaluator_type = attribute.default_edge_evaluator_type.casefold()
        if evaluator_type != "constant":
            return (
                False,
                f"Unsupported default evaluator type for {attribute.name}: {evaluator_type}",
            )
        return bool(attribute.default_edge_data), None
    if len(evaluators) != 1:
        return False, f"Ambiguous evaluators for {attribute.name} in {direction}"

    evaluator = evaluators[0]
    if evaluator.evaluator_type.casefold() != "field":
        return (
            False,
            f"Unsupported evaluator type for {attribute.name}: {evaluator.evaluator_type}",
        )
    try:
        return evaluate_field_expression(evaluator.expression, fields), None
    except ValueError as exc:
        logger.warning(
            "Could not evaluate %s in %s: %s", attribute.name, direction, exc
        )
        return False, f"{attribute.name}: {exc}"
