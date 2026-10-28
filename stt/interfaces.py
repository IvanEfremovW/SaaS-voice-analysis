"""
Интерфейсы и схемы данных для модуля транскрибации речи (STT).
Соблюдение паттернов Strategy/Adapter и архитектурных стандартов AGENTS.md.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Union
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class TranscriptionSegment(BaseModel):
    """
    Сегмент транскрибированной речи с временными метками и метаданными качества.
    """
    model_config = ConfigDict(frozen=True)

    id: int = Field(description="Порядковый номер сегмента (0, 1, 2...)")
    start: float = Field(description="Время начала сегмента в секундах (округление до 3 знаков)")
    end: float = Field(description="Время окончания сегмента в секундах (округление до 3 знаков)")
    text: str = Field(description="Очищенный текст сегмента без лишних пробелов")
    avg_logprob: float = Field(description="Средняя лог-вероятность токенов (метрика уверенности)")
    no_speech_prob: float = Field(description="Вероятность отсутствия речи в данном сегменте")


class TranscriptionResult(BaseModel):
    """
    Итоговый результат транскрибации аудиозаписи.
    """
    model_config = ConfigDict(frozen=True)

    text: str = Field(description="Полный объединенный текст звонка")
    language: str = Field(description="Распознанный язык речи (ISO 639-1 код, например, 'ru')")
    language_probability: float = Field(description="Уверенность модели в определенном языке")
    duration: float = Field(description="Длительность обработанного аудио в секундах")
    segments: List[TranscriptionSegment] = Field(
        default_factory=list,
        description="Список детализированных речевых сегментов"
    )


class BaseTranscriber(ABC):
    """
    Абстрактный базовый интерфейс транскрибатора речи (паттерн Strategy).
    Принимает путь к аудиофайлу (str | Path) или стандартизированный 1D numpy массив (float32, 16kHz).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя адаптера транскрибатора."""
        pass

    @abstractmethod
    def transcribe(
        self,
        audio: Union[str, Path, np.ndarray],
        **kwargs
    ) -> TranscriptionResult:
        """
        Транскрибирует аудиофайл или массив в текст с разметкой сегментов.

        :param audio: Путь к файлу (str, Path) или numpy массив (16kHz float32).
        :param kwargs: Дополнительные параметры инференса.
        :return: Валидированный объект TranscriptionResult.
        """
        pass
