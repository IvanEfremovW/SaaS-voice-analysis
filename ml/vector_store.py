from functools import lru_cache

from langchain_postgres import PGEngine, PGVectorStore
from sqlalchemy.exc import ProgrammingError

from config import SQLALCHEMY_URL, PGVECTOR_COLLECTION, VECTOR_SIZE
from embeddings import get_embeddings


@lru_cache(maxsize=1)
def get_vectorstore() -> PGVectorStore:
    engine = PGEngine.from_connection_string(url=SQLALCHEMY_URL)  # пул соединений с бд

    try:
        engine.init_vectorstore_table(  # создаёт таблицу под векторы
            table_name=PGVECTOR_COLLECTION,
            vector_size=VECTOR_SIZE,
        )
    except ProgrammingError as e:
        if "already exists" not in str(e):
            raise  # ошибка не про существующую таблицу — не прячем

    return PGVectorStore.create_sync(
        engine=engine,
        table_name=PGVECTOR_COLLECTION,
        embedding_service=get_embeddings(),
    )
