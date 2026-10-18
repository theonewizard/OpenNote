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
