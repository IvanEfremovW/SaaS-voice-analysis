from functools import lru_cache

from langchain_postgres import PGEngine, PGVectorStore

from config import SQLALCHEMY_URL, PGVECTOR_COLLECTION, VECTOR_SIZE
from embeddings import get_embeddings


@lru_cache(maxsize=1)
def get_vectorstore() -> PGVectorStore:
 
  
    engine = PGEngine.from_connection_string(url=SQLALCHEMY_URL)  # движок = пул соединений с PostgreSQL

    engine.init_vectorstore_table(   # таблица: вектор + текст + JSONB-колонка для метаданных
        table_name=PGVECTOR_COLLECTION,
        vector_size=VECTOR_SIZE,
    )

    return PGVectorStore.create_sync(
        engine=engine,
        table_name=PGVECTOR_COLLECTION,
        embedding_service=get_embeddings(),
    )
