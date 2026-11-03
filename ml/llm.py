from functools import lru_cache

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,  # сервер заказчика, openai-совместимый
        api_key=SecretStr(LLM_API_KEY),
        temperature=0,  # оценки должны быть стабильными
    )
