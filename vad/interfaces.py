"""
Интерфейсы детекции голосовой активности (Voice Activity Detection, VAD) (Issue #6).
Соблюдение паттернов Strategy/Adapter и архитектурных стандартов AGENTS.md.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Tuple
import numpy as np


@dataclass(frozen=True)
class SpeechSegment:
    """
    Голосовой сегмент, обнаруженный VAD (в секундах).
    """
    start: float
    end: float

    @property
    def duration(self) -> float:
        """Длительность сегмента в секундах."""
        return max(0.0, self.end - self.start)

    def to_dict(self) -> Dict[str, float]:
        """Преобразование в словарь для отчетов и JSON-сериализации."""
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3)
        }


class BaseVAD(ABC):
    """
    Базовый интерфейс детектора голосовой активности (Voice Activity Detection).
    Принимает стандартизированный 1D массив аудио (float32, 16 kHz Mono).
    Детектирует речь, вырезает паузы, возвращает склеенный голосовой поток и список интервалов.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя адаптера VAD."""
        pass

    @abstractmethod
    def process(self, audio: np.ndarray, sr: int = 16000) -> Tuple[np.ndarray, List[Dict[str, float]]]:
        """
        Детекция речи и удаление пауз/тишины.

        :param audio: 1D np.ndarray (float32, 16 kHz).
        :param sr: Частота дискретизации (по умолчанию 16000 Гц).
        :return: Кортеж (speech_only_audio, speech_segments), где:
                 - speech_only_audio: склеенный 1D np.ndarray только с участками речи
                 - speech_segments: список словарей [{'start': float, 'end': float}] в секундах
        """
        pass
