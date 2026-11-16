from typing import Any

from requirements_store import deactivate_requirement, init_requirements_table, list_requirements
from vector_store import get_vectorstore

MAX_K = 50


def get_evaluation_requirements(client_id: str = "") -> list[dict[str, Any]]:
    """Return the complete active checklist, without top-k truncation."""
    init_requirements_table()
    return list_requirements(client_id=client_id)


def deactivate_rule(requirement_id: str) -> bool:
    init_requirements_table()
    return deactivate_requirement(requirement_id)


def search_requirements(query: str, client_id: str = "", k: int = 5) -> list[dict[str, Any]]:
    k = max(1, min(k, MAX_K))
    store = get_vectorstore()
    filter_ = {"$or": [{"scope": "base"}, {"client_id": client_id}]} if client_id else {"scope": "base"}
    results = store.similarity_search_with_score(query, k=k, filter=filter_)
    return [{
        "id": doc.metadata.get("requirement_id", ""),
        "version": doc.metadata.get("version", 1),
        "title": doc.metadata.get("title", ""),
        "scope": doc.metadata.get("scope", ""),
        "client_id": doc.metadata.get("client_id", ""),
        "category": doc.metadata.get("category", ""),
        "text": doc.page_content,
        "distance": round(float(distance), 4),
    } for doc, distance in results]
