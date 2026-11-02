from typing import Dict, List

from langchain_core.documents import Document

from vector_store import get_vectorstore


def add_requirements(items: List[Dict]) -> List[str]: #принимиает требования и добавляет в бд, возвращаем список айди
  
    docs: List[Document] = []

    for item in items:
        scope = str(item.get("scope", "base")).lower().strip()
        client_id = str(item.get("client_id", "")).strip()
        category = str(item.get("category", "")).strip()
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()

        if not text:
            continue  # пустые требования не сохраняем

        page_content = f"{title}\n{text}" if title else text  # это станет вектором

        metadata = {  # это останется текстом для фильтров
            "scope": scope,
            "client_id": client_id,
            "category": category,
            "title": title,
            "source": "manual_ingest",
        }

        docs.append(Document(page_content=page_content, metadata=metadata))

    if not docs:
        return []  # если нечего сохранять

    store = get_vectorstore()
    return store.add_documents(docs)
