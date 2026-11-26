"""Локальная проверка и декодирование записей звонков."""

from math import gcd
from pathlib import Path
from typing import Protocol

import numpy as np

STANDARD_SAMPLE_RATES = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000, 176400, 192000}


class AudioDecodeError(ValueError):
    """Некорректный или неподдерживаемый аудиопоток."""


class AudioLimitError(AudioDecodeError):
    """Поток превышает лимиты декодирования."""


class AudioDecoder(Protocol):
    def inspect(self, path: Path, target_sr: int) -> None: ...

    def decode(self, path: Path, target_sr: int | None) -> tuple[np.ndarray, int]: ...


def check_resampling_cost(source: int, target: int) -> None:
    if source <= 0 or target <= 0:
        raise AudioDecodeError("Некорректная частота дискретизации")
    if source in STANDARD_SAMPLE_RATES and target in STANDARD_SAMPLE_RATES:
        return
    divisor = gcd(source, target)
    if (source // divisor) * (target // divisor) > 100_000:
        raise AudioDecodeError("Слишком дорогая комбинация частот дискретизации")


def mono_float32(audio: np.ndarray) -> np.ndarray:
    """Преобразует PCM в моно. Для 2D принимаются каналы по любой оси."""
    if audio.ndim not in (1, 2):
        raise ValueError("Ожидается одномерный или двумерный массив аудио")
    data = audio.astype(np.float32, copy=False)
    if np.issubdtype(audio.dtype, np.integer):
        bounds = np.iinfo(audio.dtype)
        if bounds.min == 0:
            midpoint = (bounds.max + 1) / 2
            data = (data - midpoint) / midpoint
        else:
            data = data / float(bounds.max)
    if data.ndim == 2:
        data = data.mean(axis=0 if data.shape[0] < data.shape[1] else 1)
    if not np.isfinite(data).all():
        raise AudioDecodeError("Аудио содержит нечисловые или бесконечные отсчёты")
    return np.clip(data, -1.0, 1.0)


class PyAVAudioDecoder(AudioDecoder):
    def __init__(self, max_seconds: float = 1800, max_samples: int = 64_000_000) -> None:
        self.max_seconds = max_seconds
        self.max_samples = max_samples

    def inspect(self, path: Path, target_sr: int) -> None:
        self._read(path, target_sr, keep_audio=False)

    def decode(self, path: Path, target_sr: int | None) -> tuple[np.ndarray, int]:
        parts, rate = self._read(path, target_sr, keep_audio=True)
        return np.clip(np.concatenate(parts), -1.0, 1.0), rate

    def _read(
        self, path: Path, target_sr: int | None, *, keep_audio: bool
    ) -> tuple[list[np.ndarray], int]:
        import av

        parts: list[np.ndarray] = []
        seconds = 0.0
        samples = 0
        source_sr = 0
        resampler = None
        output_samples = 0

        def collect(frames: list[av.AudioFrame]) -> None:
            nonlocal output_samples
            for chunk in frames:
                block = chunk.to_ndarray().reshape(-1)
                if not np.isfinite(block).all():
                    raise AudioDecodeError("Аудио содержит нечисловые или бесконечные отсчёты")
                output_samples += block.size
                if keep_audio:
                    parts.append(block)

        try:
            with path.open("rb") as source, av.open(source, options={"protocol_whitelist": "pipe"}) as container:
                if not container.streams.audio:
                    raise AudioDecodeError("Файл не содержит аудиопотока")
                for frame in container.decode(audio=0):
                    channels = len(frame.layout.channels)
                    if not 0 < frame.sample_rate <= 192000 or not 0 < channels <= 8:
                        raise AudioDecodeError("Неподдерживаемые параметры аудиопотока")
                    if resampler is None:
                        source_sr = frame.sample_rate
                        check_resampling_cost(source_sr, target_sr or source_sr)
                        resampler = av.AudioResampler(format="fltp", layout="mono", rate=target_sr or source_sr)
                    if frame.sample_rate != source_sr:
                        raise AudioDecodeError("Изменение частоты дискретизации внутри файла")
                    seconds += frame.samples / source_sr
                    samples += frame.samples * channels
                    if seconds > self.max_seconds or samples > self.max_samples:
                        raise AudioLimitError("Превышен лимит декодированного аудио")
                    collect(resampler.resample(frame))
                if resampler is None:
                    raise AudioDecodeError("Аудиопоток пуст")
                collect(resampler.resample(None))
        except AudioDecodeError:
            raise
        except (av.error.FFmpegError, OSError, ValueError) as error:
            raise AudioDecodeError("Не удалось декодировать аудиофайл") from error
        if output_samples == 0:
            raise AudioDecodeError("Аудиопоток пуст после ресемплинга")
        return parts, target_sr or source_sr
