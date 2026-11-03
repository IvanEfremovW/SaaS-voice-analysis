from typing import Dict, List

from vector_store import get_vectorstore

MAX_K = 50


def search_requirements(query: str, client_id: str = "", k: int = 5) -> List[Dict]:
    k = max(1, min(k, MAX_K))
    store = get_vectorstore()

    if client_id:
        filter_ = {"$or": [{"scope": "base"}, {"client_id": client_id}]}
    else:
        filter_ = {"scope": "base"}

    results = store.similarity_search_with_score(query, k=k, filter=filter_)

    out: List[Dict] = []
    for doc, distance in results:
        out.append(
            {
                "title": doc.metadata.get("title", ""),
                "scope": doc.metadata.get("scope", ""),
                "client_id": doc.metadata.get("client_id", ""),
                "category": doc.metadata.get("category", ""),
                "text": doc.page_content,
                "distance": round(float(distance), 4),  # меньше = ближе по смыслу
            }
        )
    return out
