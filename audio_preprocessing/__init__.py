"""
Модуль предобработки аудио (Issue #5).
Конвертация медиапотока в 16 kHz Mono float32, фильтрация шума (Denoising)
и единое ядро конвейера Preprocess + VAD.
"""

from .interfaces import BaseConverter, BaseDenoiser
from .converters import FFmpegConverter, TorchAudioConverter, LibrosaConverter
from .denoisers import (
    StationarySpectralDenoiser,
    NonStationarySpectralDenoiser,
    TelephonyBandpassDenoiser,
)
from .pipeline import (
    AudioPipelineConfig,
    AudioPipelineResult,
    AudioPreprocessVADPipeline,
    get_converter,
    get_denoiser,
    get_audio_pipeline,
    remap_time_to_original,
    remap_transcription_result,
)

__all__ = [
    # Интерфейсы
    "BaseConverter",
    "BaseDenoiser",
    # Конвертеры
    "FFmpegConverter",
    "TorchAudioConverter",
    "LibrosaConverter",
    # Шумоподавление
    "StationarySpectralDenoiser",
    "NonStationarySpectralDenoiser",
    "TelephonyBandpassDenoiser",
    # Фабрики и единый конвейер
    "get_converter",
    "get_denoiser",
    "get_audio_pipeline",
    "AudioPipelineConfig",
    "AudioPipelineResult",
    "AudioPreprocessVADPipeline",
    "remap_time_to_original",
    "remap_transcription_result",
]
