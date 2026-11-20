"""Checks on the OpenAPI document that scripts/gen-openapi.sh exports."""

from collections import Counter
from typing import Any


def duplicate_operation_ids(document: dict[str, Any]) -> list[str]:
    """operationIds that more than one operation uses; the generated clients need them unique."""
    counts = Counter(
        operation["operationId"]
        for path_item in document["paths"].values()
        for operation in path_item.values()
    )
    return sorted(operation_id for operation_id, count in counts.items() if count > 1)


_NULL = {"type": "null"}


def nullable_as_type_arrays(node: Any) -> None:
    """Rewrites Pydantic's `anyOf: [<schema with a type>, {"type": "null"}]` as that schema
    with `type: [<type>, "null"]` (and `null` added to an `enum`), in place.

    The two spell the same JSON Schema, but swift-openapi-generator does not support a
    `null` subschema: it drops every property and parameter written the first way from the
    Swift client. A `$ref` cannot take a type array, so `anyOf` with a `$ref` stays as it is.
    """
    if isinstance(node, list):
        for item in node:
            nullable_as_type_arrays(item)
    elif isinstance(node, dict):
        for value in node.values():
            nullable_as_type_arrays(value)
        options = node.get("anyOf")
        if isinstance(options, list) and len(options) == 2 and _NULL in options:
            (inner,) = (o for o in options if o != _NULL)
            if isinstance(inner.get("type"), str):
                del node["anyOf"]
                node.update(inner)
                node["type"] = [inner["type"], "null"]
                if "enum" in inner:
                    node["enum"] = [*inner["enum"], None]
