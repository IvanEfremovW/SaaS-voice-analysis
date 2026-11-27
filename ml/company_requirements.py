import json
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from langchain_core.documents import Document

from vector_store import get_company_vectorstore


def add_company_requirements(company_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    company_id = company_id.strip()
    if not company_id:
        raise ValueError("company_id must not be empty")

    docs: list[Document] = []
    vector_ids: list[str] = []
    saved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        requirement_id = str(item.get("id") or "").strip() or str(uuid4())
        if requirement_id in seen:
            raise ValueError("Duplicate company requirement ID in request")
        seen.add(requirement_id)
        title = str(item.get("title") or "").strip()
        body = str(item.get("text") or "").strip()
        if not body:
            raise ValueError("company requirement text must not be empty")
        category = str(item.get("category") or "").strip()
        content = f"{title}\n{body}" if title else body
        docs.append(Document(page_content=content, metadata={
            "rule_type": "company_requirement",
            "requirement_id": requirement_id,
            "company_id": company_id,
            "category": category,
            "title": title,
            "text": body,
            "active": True,
        }))
        # PGVectorStore uses UUID keys. The same company and rule ID can be upserted.
        key = json.dumps(["company-requirement", company_id, requirement_id])
        vector_ids.append(str(uuid5(NAMESPACE_URL, key)))
        saved.append({"id": requirement_id, "company_id": company_id,
                      "category": category, "title": title, "text": body})

    if docs:
        get_company_vectorstore().add_documents(docs, ids=vector_ids)
    return saved
