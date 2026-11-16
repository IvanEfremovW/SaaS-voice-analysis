from typing import Any

from langchain_core.documents import Document

from requirements_store import init_requirements_table, upsert_requirement
from vector_store import get_vectorstore


def add_requirements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and save requirements; each saved item has a stable ID and version."""
    init_requirements_table()
    saved: list[dict[str, Any]] = []
    docs: list[Document] = []
    store = get_vectorstore()

    for item in items:
        rule = upsert_requirement(item)
        saved.append(rule)
        if rule["previous_version"] is not None:
            store.delete(ids=[f"{rule['id']}:v{rule['previous_version']}"])
        content = f"{rule['title']}\n{rule['text']}" if rule["title"] else rule["text"]
        docs.append(Document(page_content=content, metadata={
            "requirement_id": rule["id"], "version": rule["version"],
            "active": True, "scope": rule["scope"], "client_id": rule["client_id"],
            "category": rule["category"], "title": rule["title"],
            "source": "manual_ingest",
        }))

    if docs:
        store.add_documents(docs, ids=[f"{r['id']}:v{r['version']}" for r in saved])
    for rule in saved:
        rule.pop("previous_version", None)
    return saved
