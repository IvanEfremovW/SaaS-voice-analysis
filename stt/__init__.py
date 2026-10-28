"""
Пакет транскрибации речи (Speech-to-Text, STT).
Обеспечивает слабую связанность (паттерн Strategy), фабрику get_transcriber,
конфигурацию TranscriberConfig и валидированные Pydantic DTO (TranscriptionResult, TranscriptionSegment).
"""

from typing import Optional
from .config import TranscriberConfig
from .interfaces import BaseTranscriber, TranscriptionResult, TranscriptionSegment
from .transcriber import FasterWhisperTranscriber

__all__ = [
    "BaseTranscriber",
    "FasterWhisperTranscriber",
    "TranscriberConfig",
    "TranscriptionResult",
    "TranscriptionSegment",
    "get_transcriber",
]


def get_transcriber(
    engine: str = "faster-whisper",
    config: Optional[TranscriberConfig] = None,
) -> BaseTranscriber:
    """
    Фабричная функция для создания экземпляра транскрибатора.

    :param engine: Имя STT-движка (по умолчанию 'faster-whisper').
    :param config: Объект конфигурации TranscriberConfig.
    :return: Экземпляр адаптера транскрибатора (BaseTranscriber).
    :raises ValueError: Если передан неизвестный идентификатор движка.
    """
    normalized_engine = engine.strip().lower()
    if normalized_engine in ("faster-whisper", "whisper"):
        return FasterWhisperTranscriber(config=config or TranscriberConfig())

    raise ValueError(
        f"Неизвестный STT движок: '{engine}'. Доступные варианты: ['faster-whisper']"
    )
