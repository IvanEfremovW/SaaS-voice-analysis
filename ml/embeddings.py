from functools import lru_cache
from langchain_huggingface import HuggingFaceEmbeddings
from config import EMBEDDING_MODEL, EMBEDDING_DEVICE


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": EMBEDDING_DEVICE},
        encode_kwargs={"normalize_embeddings": True},
    )
