"""
Адаптеры конвертации аудио в 16 kHz Mono float32 (Issue #5).
Реализация трех стратегий:
1. FFmpegConverter
2. TorchAudioConverter
3. LibrosaConverter
"""

import logging
import subprocess
from pathlib import Path
from typing import Tuple, Union
import numpy as np

try:
    from .interfaces import BaseConverter
except (ImportError, ValueError):
    from audio_preprocessing.interfaces import BaseConverter

logger = logging.getLogger(__name__)


class FFmpegConverter(BaseConverter):
    """
    Конвертер на базе потокового вызова FFmpeg через pipe (zero-disk overhead).
    """

    @property
    def name(self) -> str:
        return "ffmpeg"

    def convert(self, file_path: Union[Path, str], target_sr: int = 16000) -> Tuple[np.ndarray, int]:
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Аудиофайл не найден: {path}")

        cmd = [
            "ffmpeg",
            "-nostdin",
            "-threads", "1",
            "-y",
            "-i", str(path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", str(target_sr),
            "-f", "s16le",
            "pipe:1"
        ]

        logger.debug("Запуск FFmpeg: %s", " ".join(cmd))
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )

        if process.returncode != 0:
            err_msg = process.stderr.decode("utf-8", errors="replace")
            logger.error("FFmpeg ошибка при обработке %s: %s", path, err_msg)
            raise RuntimeError(f"FFmpeg failed: {err_msg}")

        # Декодирование байтов s16le в int16 -> нормализация во float32 [-1.0, 1.0]
        raw_bytes = process.stdout
        if len(raw_bytes) == 0:
            raise ValueError(f"FFmpeg вернул пустой аудиопоток для файла {path}")

        audio_int16 = np.frombuffer(raw_bytes, dtype=np.int16)
        audio_float32 = (audio_int16.astype(np.float32) / 32768.0).copy()

        return audio_float32, target_sr


class TorchAudioConverter(BaseConverter):
    """
    Конвертер на базе библиотеки PyTorch / TorchAudio.
    """

    def __init__(self):
        self._resamplers = {}

    @property
    def name(self) -> str:
        return "torchaudio"

    def convert(self, file_path: Union[Path, str], target_sr: int = 16000) -> Tuple[np.ndarray, int]:
        import torch
        import torchaudio

        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Аудиофайл не найден: {path}")

        try:
            waveform, orig_sr = torchaudio.load(str(path))
        except (ImportError, OSError, RuntimeError, Exception):
            import soundfile as sf
            data, orig_sr = sf.read(str(path), dtype="float32")
            if data.ndim == 1:
                waveform = torch.from_numpy(data).unsqueeze(0)
            else:
                waveform = torch.from_numpy(data.T)

        # Микширование в моно при необходимости
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        # Ресемплинг при несовпадении частоты
        if orig_sr != target_sr:
            if orig_sr not in self._resamplers:
                self._resamplers[orig_sr] = torchaudio.transforms.Resample(
                    orig_freq=orig_sr,
                    new_freq=target_sr
                )
            waveform = self._resamplers[orig_sr](waveform)

        audio_np = waveform.squeeze(0).cpu().numpy().astype(np.float32)
        # Ограничение диапазона [-1.0, 1.0]
        np.clip(audio_np, -1.0, 1.0, out=audio_np)

        return audio_np, target_sr


class LibrosaConverter(BaseConverter):
    """
    Конвертер на базе библиотеки Librosa
    """

    @property
    def name(self) -> str:
        return "librosa"

    def convert(self, file_path: Union[Path, str], target_sr: int = 16000) -> Tuple[np.ndarray, int]:
        import librosa

        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Аудиофайл не найден: {path}")

        audio, _ = librosa.load(str(path), sr=target_sr, mono=True)
        return audio.astype(np.float32), target_sr
