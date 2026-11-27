from typing import Any

from requirements_store import upsert_requirements


def add_requirements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Save common and administrator-specific rules in PostgreSQL only."""
    return upsert_requirements(items)
