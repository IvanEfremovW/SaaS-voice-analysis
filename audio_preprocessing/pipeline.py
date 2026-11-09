"""
Единое ядро конвейера предобработки аудио и детекции голосовой активности (Preprocess + VAD).
Реализация утвержденного R&D стека:
Входящее аудио -> TorchAudioConverter (16kHz Mono float32)
               -> StationarySpectralDenoiser
               -> SileroVADAdapter (threshold=0.5)
               -> (speech_only_audio, speech_segments)

Соблюдение паттернов Strategy/Adapter, архитектурных стандартов AGENTS.md
и полная обработка в оперативной памяти (Zero-disk I/O).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

try:
    from .interfaces import BaseConverter, BaseDenoiser
    from .converters import TorchAudioConverter, FFmpegConverter, LibrosaConverter
    from .denoisers import (
        StationarySpectralDenoiser,
        NonStationarySpectralDenoiser,
        TelephonyBandpassDenoiser,
    )
except (ImportError, ValueError):
    from audio_preprocessing.interfaces import BaseConverter, BaseDenoiser
    from audio_preprocessing.converters import (
        TorchAudioConverter,
        FFmpegConverter,
        LibrosaConverter,
    )
    from audio_preprocessing.denoisers import (
        StationarySpectralDenoiser,
        NonStationarySpectralDenoiser,
        TelephonyBandpassDenoiser,
    )

try:
    from vad import get_vad, BaseVAD
except (ImportError, ValueError):
    from ..vad import get_vad, BaseVAD

logger = logging.getLogger(__name__)


def get_converter(name: str = "torchaudio") -> BaseConverter:
    """
    Фабрика создания конвертера медиафайлов в стандартизированный поток 16 kHz Mono float32.

    :param name: Имя конвертера: 'torchaudio', 'ffmpeg', 'librosa'.
    :return: Экземпляр BaseConverter.
    :raises ValueError: Если передано неизвестное имя конвертера.
    """
    if not isinstance(name, str):
        raise ValueError(f"Имя конвертера должно быть строкой, получено: {type(name).__name__}")

    clean_name = name.strip().lower()
    if clean_name == "torchaudio":
        return TorchAudioConverter()
    elif clean_name == "ffmpeg":
        return FFmpegConverter()
    elif clean_name == "librosa":
        return LibrosaConverter()
    else:
        raise ValueError(
            f"Неизвестный конвертер: '{name}'. "
            "Поддерживаются: 'torchaudio', 'ffmpeg', 'librosa'"
        )


def get_denoiser(name: Optional[str] = "stat_spectral", **kwargs: Any) -> Optional[BaseDenoiser]:
    """
    Фабрика создания алгоритма шумоподавления (Denoising).

    :param name: Имя шумодава: 'stat_spectral', 'nonstat_spectral', 'telephony_bandpass' или 'none' / None.
    :param kwargs: Дополнительные параметры конфигурации шумодава.
    :return: Экземпляр BaseDenoiser или None, если шумодав отключен.
    :raises ValueError: Если передано неизвестное имя шумодава.
    """
    if name is None:
        return None

    if not isinstance(name, str):
        raise ValueError(f"Имя шумодава должно быть строкой или None, получено: {type(name).__name__}")

    clean_name = name.strip().lower()
    if clean_name in ("none", ""):
        return None

    if clean_name == "stat_spectral":
        return StationarySpectralDenoiser(**kwargs)
    elif clean_name == "nonstat_spectral":
        return NonStationarySpectralDenoiser(**kwargs)
    elif clean_name == "telephony_bandpass":
        return TelephonyBandpassDenoiser(**kwargs)
    else:
        raise ValueError(
            f"Неизвестный алгоритм шумоподавления: '{name}'. "
            "Поддерживаются: 'stat_spectral', 'nonstat_spectral', 'telephony_bandpass', 'none' / None"
        )


class AudioPipelineConfig(BaseModel):
    """
    Конфигурация конвейера предобработки и VAD.
    """
    model_config = ConfigDict(extra="ignore")

    target_sr: int = Field(default=16000, ge=8000, le=48000)
    converter: str = Field(default="torchaudio", description="Конвертер: torchaudio | ffmpeg | librosa")
    denoiser: Optional[str] = Field(
        default="stat_spectral",
        description="Шумодав: stat_spectral | nonstat_spectral | telephony_bandpass | none"
    )
    vad: Optional[str] = Field(default="silero", description="VAD: silero | webrtc | energy | none")
    denoiser_kwargs: Dict[str, Any] = Field(default_factory=dict)
    vad_kwargs: Dict[str, Any] = Field(default_factory=dict)


class AudioPipelineResult(BaseModel):
    """
    Детальный результат выполнения конвейера предобработки и VAD.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    speech_only_audio: np.ndarray = Field(description="Склеенное аудио только с участками речи (1D float32)")
    speech_segments: List[Dict[str, float]] = Field(
        default_factory=list,
        description="Временные интервалы речи относительно исходного файла [{'start': float, 'end': float}]"
    )
    sample_rate: int = Field(default=16000, description="Частота дискретизации аудио")
    original_duration: float = Field(description="Длительность исходного аудио в секундах")
    speech_duration: float = Field(description="Длительность речи после VAD в секундах")
    retention_pct: float = Field(description="Процент удержания речи (0..100%)")


class AudioPreprocessVADPipeline:
    """
    Единый конвейер предобработки входящего аудиопотока и детекции речи (VAD).
    Работает полностью в памяти (Zero-disk I/O).
    """

    def __init__(self, config: Optional[AudioPipelineConfig] = None) -> None:
        self.config = config or AudioPipelineConfig()
        self.converter: BaseConverter = get_converter(self.config.converter)
        self.denoiser: Optional[BaseDenoiser] = get_denoiser(
            self.config.denoiser, **self.config.denoiser_kwargs
        )
        self.vad: Optional[BaseVAD] = get_vad(
            self.config.vad, **self.config.vad_kwargs
        )
        logger.debug(
            "Инициализирован AudioPreprocessVADPipeline: converter=%s, denoiser=%s, vad=%s, target_sr=%d",
            self.converter.name,
            self.denoiser.name if self.denoiser else "none",
            self.vad.name if self.vad else "none",
            self.config.target_sr,
        )

    def process_detailed(
        self,
        audio_source: Union[str, Path, np.ndarray],
        sr: int = 16000
    ) -> AudioPipelineResult:
        """
        Выполняет полный цикл предобработки и VAD в оперативной памяти (Zero-disk I/O).

        :param audio_source: Путь к медиафайлу (str | Path) или 1D/2D numpy массив.
        :param sr: Частота дискретизации (если передан numpy массив).
        :return: Детализированный результат AudioPipelineResult.
        """
        target_sr = self.config.target_sr

        # 1. Загрузка и приведение к 1D float32 моно
        if isinstance(audio_source, (str, Path)):
            path = Path(audio_source).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Аудиофайл не найден: {path}")
            audio, _ = self.converter.convert(path, target_sr=target_sr)
        elif isinstance(audio_source, np.ndarray):
            audio = audio_source
            if audio.size == 0:
                return AudioPipelineResult(
                    speech_only_audio=np.empty((0,), dtype=np.float32),
                    speech_segments=[],
                    sample_rate=target_sr,
                    original_duration=0.0,
                    speech_duration=0.0,
                    retention_pct=0.0,
                )

            # Микширование в моно
            if audio.ndim == 2:
                if audio.shape[0] in (1, 2) and audio.shape[1] > audio.shape[0]:
                    audio = np.mean(audio, axis=0)
                elif audio.shape[1] in (1, 2) and audio.shape[0] > audio.shape[1]:
                    audio = np.mean(audio, axis=1)
                else:
                    audio = audio.flatten()
            elif audio.ndim > 2:
                audio = audio.flatten()

            # Нормализация типов
            if np.issubdtype(audio.dtype, np.integer):
                max_val = float(np.iinfo(audio.dtype).max)
                audio = (audio / max_val).astype(np.float32)
            elif audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            # Ограничение диапазона амплитуды
            audio = np.clip(audio, -1.0, 1.0)

            # Ресемплинг при несовпадении частоты
            if sr != target_sr and len(audio) > 0:
                import torch
                import torchaudio
                resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)
                tensor = torch.from_numpy(audio).unsqueeze(0)
                audio = resampler(tensor).squeeze(0).numpy().astype(np.float32)
                np.clip(audio, -1.0, 1.0, out=audio)
        else:
            raise TypeError(
                f"Неподдерживаемый тип аудиоисточника: {type(audio_source)}. "
                "Ожидается str, pathlib.Path или numpy.ndarray."
            )

        orig_duration = round(float(len(audio) / target_sr), 3) if len(audio) > 0 else 0.0

        # 2. Шумоподавление (Denoising)
        if self.denoiser is not None and len(audio) > 0:
            audio = self.denoiser.denoise(audio, sr=target_sr)
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

        # 3. Детекция голосовой активности (VAD)
        if self.vad is not None:
            speech_only_audio, speech_segments = self.vad.process(audio, sr=target_sr)
        else:
            speech_only_audio = audio
            speech_segments = [{"start": 0.0, "end": orig_duration}]

        # Вычисление продолжительности и коэффициента удержания
        speech_duration = round(float(len(speech_only_audio) / target_sr), 3) if len(speech_only_audio) > 0 else 0.0
        retention_pct = round(float((speech_duration / orig_duration * 100.0) if orig_duration > 0 else 0.0), 2)
        retention_pct = min(100.0, max(0.0, retention_pct))

        return AudioPipelineResult(
            speech_only_audio=speech_only_audio,
            speech_segments=speech_segments,
            sample_rate=target_sr,
            original_duration=orig_duration,
            speech_duration=speech_duration,
            retention_pct=retention_pct,
        )

    def process(
        self,
        audio_source: Union[str, Path, np.ndarray],
        sr: int = 16000
    ) -> Tuple[np.ndarray, List[Dict[str, float]]]:
        """
        Вызывает process_detailed и возвращает компактный кортеж (speech_only_audio, speech_segments).

        :param audio_source: Путь к медиафайлу или numpy массив.
        :param sr: Частота дискретизации.
        :return: Кортеж (1D float32 массив речи, список интервалов [{'start': float, 'end': float}]).
        """
        res = self.process_detailed(audio_source, sr=sr)
        return res.speech_only_audio, res.speech_segments


def remap_time_to_original(
    compact_time: float,
    speech_segments: List[Dict[str, float]],
    is_end: bool = False
) -> float:
    """
    Пересчитывает время (в секундах) внутри склеенного speech_only_audio
    обратно на реальную временную шкалу исходного аудиофайла по списку speech_segments.

    :param compact_time: Время в секундах в компактном аудиопотоке.
    :param speech_segments: Список сегментов вида [{'start': float, 'end': float}].
    :param is_end: Флаг, является ли метка концом интервала (на стыке сегментов
                   возвращает конец предыдущего сегмента вместо начала следующего).
    :return: Время в секундах на исходной шкале времени.
    """
    if not speech_segments:
        return max(0.0, round(compact_time, 3))

    if compact_time <= 0.0:
        return round(float(speech_segments[0]["start"]), 3)

    elapsed = 0.0
    num_segs = len(speech_segments)

    for i, seg in enumerate(speech_segments):
        start = float(seg["start"])
        end = float(seg["end"])
        dur = max(0.0, end - start)
        seg_end_compact = elapsed + dur

        is_last = (i == num_segs - 1)

        # Граничное условие:
        # Для конца сегмента (is_end=True) граница включена (<=)
        # Для начала (is_end=False) внутренняя граница строгая (<), за исключением последнего сегмента
        condition = (compact_time <= seg_end_compact) if (is_end or is_last) else (compact_time < seg_end_compact)
        if condition:
            offset = max(0.0, min(compact_time - elapsed, dur))
            return round(start + offset, 3)

        elapsed = seg_end_compact

    # Если значение превышает общую длину сегментов — возвращаем конец последнего
    return round(float(speech_segments[-1]["end"]), 3)


def get_audio_pipeline(
    config: Optional[AudioPipelineConfig] = None
) -> AudioPreprocessVADPipeline:
    """
    Фабрика создания единого конвейера Preprocess + VAD.

    :param config: Опциональная конфигурация конвейера.
    :return: Настроенный экземпляр AudioPreprocessVADPipeline.
    """
    return AudioPreprocessVADPipeline(config=config)
