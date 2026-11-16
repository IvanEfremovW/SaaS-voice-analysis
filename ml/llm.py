from functools import lru_cache

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    """OpenAI-compatible model adapter; switch endpoint/model through environment."""
    if not LLM_BASE_URL:
        raise RuntimeError("LLM_BASE_URL must point to the configured Qwen-compatible API")
    return ChatOpenAI(
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        api_key=SecretStr(LLM_API_KEY or "not-required"),
        temperature=0,
        timeout=240,
        max_retries=2,
    )
