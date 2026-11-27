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
    """Create or migrate the table while preserving legacy company IDs."""
    with get_engine().begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(187351, 1)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_requirements (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL DEFAULT 'base',
                administrator_id TEXT NOT NULL DEFAULT '',
                client_id TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        migrated = conn.scalar(text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'rag_requirements'::regclass
                  AND conname = 'rag_requirements_rule_scope_ck'
            )
        """))
        if not migrated:
            conn.execute(text("""
                ALTER TABLE rag_requirements
                    ADD COLUMN IF NOT EXISTS administrator_id TEXT NOT NULL DEFAULT '',
                    DROP CONSTRAINT IF EXISTS rag_requirements_scope_check,
                    DROP CONSTRAINT IF EXISTS rag_requirements_scope_ck
            """))
            # The prototype copied company IDs into administrator_id. Keep those
            # records available for explicit reassignment or import.
            conn.execute(text("""
                UPDATE rag_requirements
                SET scope = 'client', administrator_id = ''
                WHERE client_id <> '' AND (
                    scope = 'base' OR (scope = 'administrator' AND administrator_id = client_id)
                )
            """))
            conn.execute(text("""
                ALTER TABLE rag_requirements
                    ADD CONSTRAINT rag_requirements_rule_scope_ck
                        CHECK (scope IN ('base', 'administrator', 'client')),
                    ADD CONSTRAINT rag_requirements_rule_owner_ck
                        CHECK (scope <> 'administrator' OR administrator_id <> '')
            """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rag_requirements_scope_admin ON rag_requirements (scope, administrator_id, active)"))


def _prepare_rule(item: dict[str, Any]) -> dict[str, Any]:
    requirement_id = str(item.get("id") or "").strip() or str(uuid4())
    administrator_id = str(item.get("administrator_id") or "").strip()
    scope = str(item.get("scope") or ("administrator" if administrator_id else "base")).strip().lower()
    if item.get("client_id") or scope == "client":
        raise ValueError("Use administrator_id for personal rules or /company-requirements for company rules")
    if scope not in {"base", "administrator"}:
        raise ValueError("scope must be 'base' or 'administrator'")
    if scope == "administrator" and not administrator_id:
        raise ValueError("administrator_id is required for administrator-specific requirements")
    if scope == "base" and administrator_id:
        raise ValueError("base requirements must not have an administrator_id")
    body = str(item.get("text") or "").strip()
    if not body:
        raise ValueError("text must not be empty")
    title = str(item.get("title") or "").strip()
    category = str(item.get("category") or "").strip()

    return {"id": requirement_id, "scope": scope, "administrator_id": administrator_id,
            "category": category, "title": title, "text": body}


def upsert_requirements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules = [_prepare_rule(item) for item in items]
    if len({rule["id"] for rule in rules}) != len(rules):
        raise ValueError("Duplicate requirement ID in request")
    init_requirements_table()
    statement = text("""
        INSERT INTO rag_requirements (id, scope, administrator_id, client_id, category, title, body)
        VALUES (:id, :scope, :administrator_id, '', :category, :title, :text)
        ON CONFLICT (id) DO UPDATE SET
            scope = EXCLUDED.scope, administrator_id = EXCLUDED.administrator_id,
            client_id = '', category = EXCLUDED.category, title = EXCLUDED.title,
            body = EXCLUDED.body, version = rag_requirements.version + 1,
            active = TRUE, updated_at = now()
        RETURNING version, active
    """)
    with get_engine().begin() as conn:
        # Take locks in the same order for concurrent batches.
        for rule in sorted(rules, key=lambda rule: rule["id"]):
            rule.update(conn.execute(statement, rule).mappings().one())
    return rules


def list_requirements(administrator_id: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
    administrator_id = administrator_id.strip()
    conditions = ["scope = 'base'"]
    if administrator_id:
        conditions = ["(scope = 'base' OR (scope = 'administrator' AND administrator_id = :administrator_id))"]
    params: dict[str, Any] = {"administrator_id": administrator_id} if administrator_id else {}
    if not include_inactive:
        conditions.append("active = TRUE")
    with get_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, scope, administrator_id, category, title, body AS text, version, active,
                   created_at, updated_at
            FROM rag_requirements WHERE {' AND '.join(conditions)}
            ORDER BY scope, category, title, id
        """), params).mappings().all()
    return [dict(row) for row in rows]


def deactivate_requirement(requirement_id: str) -> bool:
    with get_engine().begin() as conn:
        result = conn.execute(text("""
            UPDATE rag_requirements SET active = FALSE, updated_at = now()
            WHERE id = :id AND active = TRUE AND scope IN ('base', 'administrator')
        """), {"id": requirement_id})
    return result.rowcount > 0
