"""
Интерфейсы и протоколы для оркестратора конвейера обработки звонков (Orchestrator).
Соблюдение принципов Dependency Inversion (IoC), чистой архитектуры и паттерна Adapter.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Protocol, Tuple, Union, runtime_checkable
import numpy as np
from stt.interfaces import TranscriptionResult


class BaseAudioLoader(ABC):
    """
    Абстрактный базовый загрузчик аудиозаписей звонков (CRM-адаптер / локальное хранилище / S3).
    Инкапсулирует получение аудиофайла и приведение к стандартному представлению.
    """

    @abstractmethod
    def load(self, call_id_or_path: Union[str, Path]) -> Tuple[np.ndarray, int]:
        """
        Загружает аудиозапись звонка по ID или пути к файлу.

        :param call_id_or_path: Идентификатор звонка в CRM или путь к локальному медиафайлу.
        :return: Кортеж (1D float32 numpy-массив моно-аудио, частота дискретизации в Гц).
        """
        pass


@runtime_checkable
class BasePreprocessorProtocol(Protocol):
    """
    Протокол сервиса предобработки аудио и VAD.
    Поддерживает как in-memory AudioPreprocessVADPipeline, так и сетевой RestPreprocessorClient.
    """

    def process(
        self,
        audio_source: Union[str, Path, np.ndarray],
        sr: int = 16000,
    ) -> Tuple[np.ndarray, List[Dict[str, float]]]:
        """
        Выполняет предобработку и VAD-сегментацию.

        :param audio_source: Путь к медиафайлу или numpy массив.
        :param sr: Частота дискретизации входного аудио.
        :return: Кортеж (speech_only_audio 1D float32, speech_segments [{'start': float, 'end': float}]).
        """
        ...


@runtime_checkable
class BaseTranscriberProtocol(Protocol):
    """
    Протокол сервиса транскрибации речи (STT).
    Поддерживает как in-memory BaseTranscriber (Whisper), так и сетевой RestTranscriberClient.
    """

    def transcribe(
        self,
        audio: Union[str, Path, np.ndarray],
        **kwargs: Any,
    ) -> TranscriptionResult:
        """
        Транскрибирует аудио в текст с разметкой сегментов.

        :param audio: Входное аудио (массив или путь).
        :param kwargs: Дополнительные параметры транскрибации (язык, beam_size и т.д.).
        :return: Валидированный TranscriptionResult.
        """
        ...
