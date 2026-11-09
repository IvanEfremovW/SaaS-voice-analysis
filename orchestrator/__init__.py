"""
Модуль оркестратора обработки звонков (Orchestrator).
Обеспечивает сквозное управление конвейером между изолированными «чёрными ящиками»
(Audio Preprocessing / VAD, Speech-to-Text) через композицию зависимостей (IoC).
"""

from .interfaces import (
    BaseAudioLoader,
    BasePreprocessorProtocol,
    BaseTranscriberProtocol,
)
from .loaders import LocalMockAudioLoader
from .rest_clients import RestPreprocessorClient, RestTranscriberClient
from .pipeline import (
    CallProcessingPipeline,
    remap_time_to_original,
    remap_transcription_result,
)

__all__ = [
    # Интерфейсы
    "BaseAudioLoader",
    "BasePreprocessorProtocol",
    "BaseTranscriberProtocol",
    # Загрузчики
    "LocalMockAudioLoader",
    # REST-клиенты
    "RestPreprocessorClient",
    "RestTranscriberClient",
    # Оркестратор и утилиты маппинга
    "CallProcessingPipeline",
    "remap_time_to_original",
    "remap_transcription_result",
]
