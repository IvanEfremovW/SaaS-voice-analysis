"""
Модуль предобработки аудио (Issue #5).
Конвертация медиапотока в 16 kHz Mono float32 и фильтрация шума (Denoising).
"""

from .interfaces import BaseConverter, BaseDenoiser
from .converters import FFmpegConverter, TorchAudioConverter, LibrosaConverter
from .denoisers import (
    StationarySpectralDenoiser,
    NonStationarySpectralDenoiser,
    TelephonyBandpassDenoiser,
)

__all__ = [
    "BaseConverter",
    "BaseDenoiser",
    "FFmpegConverter",
    "TorchAudioConverter",
    "LibrosaConverter",
    "StationarySpectralDenoiser",
    "NonStationarySpectralDenoiser",
    "TelephonyBandpassDenoiser"
]
