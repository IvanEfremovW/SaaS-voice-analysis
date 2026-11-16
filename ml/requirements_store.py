from __future__ import annotations

from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import SQLALCHEMY_URL


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(SQLALCHEMY_URL, pool_pre_ping=True)
    return _engine


@lru_cache(maxsize=1)
def init_requirements_table() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_requirements (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL CHECK (scope IN ('base', 'client')),
                client_id TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CHECK (scope <> 'client' OR client_id <> '')
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rag_requirements_scope_client ON rag_requirements (scope, client_id, active)"))


def upsert_requirement(item: dict[str, Any]) -> dict[str, Any]:
    requirement_id = str(item.get("id") or uuid4())
    scope = str(item.get("scope") or ("client" if item.get("client_id") else "base")).strip().lower()
    if scope not in {"base", "client"}:
        raise ValueError("scope must be 'base' or 'client'")
    client_id = str(item.get("client_id") or "").strip()
    if scope == "client" and not client_id:
        raise ValueError("client_id is required for client-scoped requirements")
    body = str(item.get("text") or "").strip()
    if not body:
        raise ValueError("text must not be empty")
    title = str(item.get("title") or "").strip()
    category = str(item.get("category") or "").strip()

    previous_version = None
    with get_engine().begin() as conn:
        existing = conn.execute(
            text("SELECT version FROM rag_requirements WHERE id = :id"), {"id": requirement_id}
        ).mappings().first()
        previous_version = int(existing["version"]) if existing else None
        version = previous_version + 1 if previous_version else 1
        conn.execute(text("""
            INSERT INTO rag_requirements (id, scope, client_id, category, title, body, version, active, created_at, updated_at)
            VALUES (:id, :scope, :client_id, :category, :title, :body, :version, TRUE, now(), now())
            ON CONFLICT (id) DO UPDATE SET
                scope = EXCLUDED.scope, client_id = EXCLUDED.client_id,
                category = EXCLUDED.category, title = EXCLUDED.title,
                body = EXCLUDED.body, version = EXCLUDED.version,
                active = TRUE, updated_at = now()
        """), {
            "id": requirement_id, "scope": scope, "client_id": client_id,
            "category": category, "title": title, "body": body, "version": version,
        })
    return {"id": requirement_id, "scope": scope, "client_id": client_id, "category": category,
            "title": title, "text": body, "version": version, "previous_version": previous_version, "active": True}


def list_requirements(client_id: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    conditions = ["(scope = 'base' OR client_id = :client_id)"] if client_id else ["scope = 'base'"]
    params: dict[str, Any] = {"client_id": client_id} if client_id else {}
    if not include_inactive:
        conditions.append("active = TRUE")
    with get_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, scope, client_id, category, title, body AS text, version, active,
                   created_at, updated_at
            FROM rag_requirements WHERE {' AND '.join(conditions)}
            ORDER BY scope, category, title, id
        """), params).mappings().all()
    return [dict(row) for row in rows]


def deactivate_requirement(requirement_id: str) -> bool:
    with get_engine().begin() as conn:
        result = conn.execute(text("UPDATE rag_requirements SET active = FALSE, updated_at = now() WHERE id = :id AND active = TRUE"), {"id": requirement_id})
    return result.rowcount > 0
