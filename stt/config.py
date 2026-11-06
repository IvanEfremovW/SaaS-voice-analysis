"""
Конфигурация параметров модели транскрибации речи (STT).
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


DEFAULT_MODEL_SIZE = "small"


class TranscriberConfig(BaseModel):
    """
    Конфигурация параметров инференса модели транскрибации Whisper.
    """
    model_size: str = Field(
        default=DEFAULT_MODEL_SIZE,
        description="Размер модели Whisper (например, 'tiny', 'base', 'small', 'medium', 'large-v3')"
    )
    device: Literal["cuda", "cpu", "auto"] = Field(
        default="cuda",
        description="Целевое вычислительное устройство: 'cuda', 'cpu' или 'auto'"
    )
    device_index: int = Field(
        default=0,
        ge=0,
        description="Индекс GPU-устройства (0, 1, ...)"
    )
    compute_type: str = Field(
        default="float16",
        description="Тип вычислений и квантования ('float16', 'int8', 'float32', 'int8_float16')"
    )
    language: Optional[str] = Field(
        default="ru",
        description="Языковой код аудио (двухбуквенный ISO код, 'ru') или None для автоопределения"
    )
    beam_size: int = Field(
        default=5,
        ge=1,
        description="Размер лучевого поиска (beam search)"
    )
    vad_filter: bool = Field(
        default=False,
        description="Использовать ли встроенный VAD фильтр Whisper (по умолчанию False, т.к. используется отдельный модуль vad/)"
    )
    condition_on_previous_text: bool = Field(
        default=False,
        description="Защита от зацикливания и повторов на паузах"
    )
    initial_prompt: Optional[str] = Field(
        default=None,
        description="Начальный промпт/контекст для повышения точности терминов"
    )
