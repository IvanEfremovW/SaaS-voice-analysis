"""
Модуль детекции голосовой активности (Voice Activity Detection, VAD) (Issue #6).
Вырезание пауз и тишины, таймкоды речевых сегментов для модели транскрибации Whisper.
"""

from typing import Optional
from .interfaces import BaseVAD, SpeechSegment
from .vads import SileroVADAdapter, WebRTCVADAdapter, EnergyVADAdapter


def get_vad(name: Optional[str] = "silero", **kwargs) -> Optional[BaseVAD]:
    """
    Фабрика создания экземпляра VAD детектора (паттерн Strategy).

    :param name: Имя VAD детектора: 'silero', 'webrtc', 'energy' или 'none' / None.
    :param kwargs: Дополнительные параметры инициализации (например, threshold=0.5).
    :return: Экземпляр BaseVAD или None, если VAD отключен.
    :raises ValueError: Если передано неизвестное имя VAD.
    """
    if name is None:
        return None

    if not isinstance(name, str):
        raise ValueError(f"Имя VAD должно быть строкой или None, получено: {type(name).__name__}")

    clean_name = name.strip().lower()
    if clean_name in ("none", ""):
        return None

    if clean_name == "silero":
        return SileroVADAdapter(**kwargs)
    elif clean_name == "webrtc":
        return WebRTCVADAdapter(**kwargs)
    elif clean_name == "energy":
        return EnergyVADAdapter(**kwargs)
    else:
        raise ValueError(
            f"Неизвестный VAD алгоритм: '{name}'. "
            "Поддерживаются: 'silero', 'webrtc', 'energy', 'none' / None"
        )


__all__ = [
    "BaseVAD",
    "SpeechSegment",
    "SileroVADAdapter",
    "WebRTCVADAdapter",
    "EnergyVADAdapter",
    "get_vad",
]
