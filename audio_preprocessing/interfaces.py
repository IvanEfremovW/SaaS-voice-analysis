"""
Интерфейсы для модульной предобработки аудио (Issue #5).
Соблюдение паттернов Strategy/Adapter и архитектурных стандартов AGENTS.md.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple, Union
import numpy as np


class BaseConverter(ABC):
    """
    Базовый интерфейс конвертера медиафайлов в стандартизированный аудиопоток.
    Принимает путь к аудиофайлу любого формата (WAV, MP3, OGG, AAC, M4A, FLAC),
    преобразует в 1D numpy массив float32 с частотой target_sr (по умолчанию 16 kHz Mono).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя адаптера конвертации."""
        pass

    @abstractmethod
    def convert(self, file_path: Union[Path, str], target_sr: int = 16000) -> Tuple[np.ndarray, int]:
        """
        Загрузка и конвертация медиафайла в моно float32 с частотой target_sr.

        :param file_path: Путь к исходному аудиофайлу.
        :param target_sr: Целевая частота дискретизации (Гц).
        :return: Кортеж (audio_array, sample_rate), где audio_array — 1D np.ndarray (float32, диапазон [-1.0, 1.0]).
        """
        pass


class BaseDenoiser(ABC):
    """
    Базовый интерфейс фильтрации шума (Denoising).
    Принимает нормализованный аудиосигнал 16 kHz mono, возвращает очищенный массив.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя адаптера шумоподавления."""
        pass

    @abstractmethod
    def denoise(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        Очистка сигнала от шума.

        :param audio: 1D np.ndarray (float32, 16 kHz).
        :param sr: Частота дискретизации (по умолчанию 16000).
        :return: Очищенный 1D np.ndarray (float32, 16 kHz).
        """
        pass
