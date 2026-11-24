from functools import lru_cache

from langchain_postgres import PGEngine, PGVectorStore
from sqlalchemy import inspect, text

from config import COMPANY_PGVECTOR_COLLECTION, SQLALCHEMY_URL, VECTOR_SIZE
from embeddings import get_embeddings
from requirements_store import get_engine


@lru_cache(maxsize=1)
def get_company_vectorstore() -> PGVectorStore:
    """Open the vector table for company requirements."""
    # Serialize initial table creation across API workers and replicas.
    with get_engine().begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(187351, 2)"))
        engine = PGEngine.from_connection_string(url=SQLALCHEMY_URL, pool_pre_ping=True)
        if not inspect(connection).has_table(COMPANY_PGVECTOR_COLLECTION, schema="public"):
            engine.init_vectorstore_table(
                table_name=COMPANY_PGVECTOR_COLLECTION,
                vector_size=VECTOR_SIZE,
            )

    return PGVectorStore.create_sync(
        engine=engine,
        table_name=COMPANY_PGVECTOR_COLLECTION,
        embedding_service=get_embeddings(),
    )
