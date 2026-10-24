"""
Модуль детекции голосовой активности (Voice Activity Detection, VAD) (Issue #6).
Вырезание пауз и тишины, таймкоды речевых сегментов для модели транскрибации Whisper.
"""

from .interfaces import BaseVAD, SpeechSegment
from .vads import SileroVADAdapter, WebRTCVADAdapter, EnergyVADAdapter

__all__ = [
    "BaseVAD",
    "SpeechSegment",
    "SileroVADAdapter",
    "WebRTCVADAdapter",
    "EnergyVADAdapter",
]
