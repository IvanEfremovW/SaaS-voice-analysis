from typing import Any

from requirements_store import deactivate_requirement, init_requirements_table, list_requirements
from vector_store import get_company_vectorstore

MAX_K = 50
TRANSCRIPT_CHUNK_CHARS = 1200
TRANSCRIPT_CHUNK_OVERLAP = 200


def _split_transcript(text: str) -> list[str]:
    """Split long transcripts so the embedding model can see the whole call."""
    text = text.strip()
    if len(text) <= TRANSCRIPT_CHUNK_CHARS:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + TRANSCRIPT_CHUNK_CHARS, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + 600, end), text.rfind(" ", start + 600, end))
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - TRANSCRIPT_CHUNK_OVERLAP)
    return chunks


def deactivate_rule(requirement_id: str) -> bool:
    init_requirements_table()
    return deactivate_requirement(requirement_id)


def search_company_requirements(query: str, company_id: str, k: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if not company_id.strip():
        raise ValueError("company_id is required for company requirement search")
    k = max(1, min(k, MAX_K))
    filter_ = {"$and": [
        {"rule_type": "company_requirement"},
        {"active": True},
        {"company_id": company_id.strip()},
    ]}
    results = get_company_vectorstore().similarity_search_with_score(query, k=k, filter=filter_)
    return [{
        "id": f"company:{doc.metadata.get('requirement_id', '')}",
        "version": doc.metadata.get("version", 1),
        "title": doc.metadata.get("title", ""),
        "scope": "company",
        "company_id": doc.metadata.get("company_id", ""),
        "category": doc.metadata.get("category", ""),
        "text": doc.metadata.get("text", doc.page_content),
        "distance": float(distance),
    } for doc, distance in results]


def get_rules_for_administrator(administrator_id: str = "") -> list[dict[str, Any]]:
    init_requirements_table()
    return list_requirements(administrator_id=administrator_id)


def search_company_requirements_for_transcript(
    transcript: str, company_id: str, k: int = 10
) -> list[dict[str, Any]]:
    """Search transcript chunks against only the selected company's vector rules."""
    k = max(1, min(k, MAX_K))
    chunks = _split_transcript(transcript)
    matches: dict[tuple[str, int], dict[str, Any]] = {}

    for chunk in chunks:
        results = search_company_requirements(chunk, company_id=company_id, k=k)
        for item in results:
            key = (item["id"], int(item["version"]))
            existing = matches.get(key)
            if existing is None:
                item["matched_chunks"] = 1
                matches[key] = item
            else:
                existing["matched_chunks"] += 1
                existing["distance"] = min(existing["distance"], item["distance"])

    ranked = sorted(matches.values(), key=lambda item: (item["distance"], -item["matched_chunks"]))
    return ranked[:k]
