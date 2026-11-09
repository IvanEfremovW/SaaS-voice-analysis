"""
Адаптеры шумоподавления (Denoising) для аудио 16 kHz Mono (Issue #5).
Реализация трех стратегий:
1. StationarySpectralDenoiser (noisereduce stationary=True + нормализация уровня)
2. NonStationarySpectralDenoiser (noisereduce stationary=False + нормализация уровня)
3. TelephonyBandpassDenoiser (полосовой фильтр Баттерворта 300-3400 Гц + нормализация уровня)
"""

import logging
from typing import Optional
import numpy as np
from scipy import signal

try:
    from .interfaces import BaseDenoiser
except (ImportError, ValueError):
    from audio_preprocessing.interfaces import BaseDenoiser

logger = logging.getLogger(__name__)


def _normalize_audio(audio: np.ndarray, target_peak: float = 0.9) -> np.ndarray:
    """
    Безопасная нормализация пиковой громкости аудиосигнала.
    Предотвращает эффект «слишком тихой записи» и клиппинг.
    """
    if len(audio) == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak > 1e-4:
        return (audio * (target_peak / peak)).astype(np.float32)
    return audio.astype(np.float32)


class StationarySpectralDenoiser(BaseDenoiser):
    """
    Стационарное спектральное шумоподавление на базе noisereduce.
    """

    def __init__(self, prop_decrease: float = 0.85, normalize: bool = True):
        self.prop_decrease = prop_decrease
        self.normalize = normalize

    @property
    def name(self) -> str:
        return "stat_spectral"

    def denoise(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        import noisereduce as nr

        if len(audio) == 0:
            return audio

        cleaned = nr.reduce_noise(
            y=audio,
            sr=sr,
            stationary=True,
            prop_decrease=self.prop_decrease
        ).astype(np.float32)

        if self.normalize:
            cleaned = _normalize_audio(cleaned, target_peak=0.9)

        return cleaned


class NonStationarySpectralDenoiser(BaseDenoiser):
    """
    Нестационарное спектральное шумоподавление на базе noisereduce.
    """

    def __init__(self, prop_decrease: float = 0.85, normalize: bool = True):
        self.prop_decrease = prop_decrease
        self.normalize = normalize

    @property
    def name(self) -> str:
        return "nonstat_spectral"

    def denoise(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        import noisereduce as nr

        if len(audio) == 0:
            return audio

        cleaned = nr.reduce_noise(
            y=audio,
            sr=sr,
            stationary=False,
            prop_decrease=self.prop_decrease
        ).astype(np.float32)

        if self.normalize:
            cleaned = _normalize_audio(cleaned, target_peak=0.9)

        return cleaned


class TelephonyBandpassDenoiser(BaseDenoiser):
    """
    Шумоподавление методом телефонической полосовой фильтрации Баттерворта (300–3400 Гц).
    Чисто и мгновенно вырезает низкочастотные сетевые наводки (<300 Гц)
    и высокочастотный шум телефонного тракта (>3400 Гц).
    """

    def __init__(self, low_freq: float = 300.0, high_freq: float = 3400.0, order: int = 4, normalize: bool = True):
        self.low_freq = low_freq
        self.high_freq = high_freq
        self.order = order
        self.normalize = normalize

    @property
    def name(self) -> str:
        return "telephony_bandpass"

    def denoise(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        if len(audio) == 0:
            return audio

        nyq = 0.5 * sr
        low = max(50.0, self.low_freq) / nyq
        high = min(0.95 * nyq, self.high_freq) / nyq
        b, a = signal.butter(self.order, [low, high], btype="band")
        filtered = signal.filtfilt(b, a, audio).astype(np.float32)

        if self.normalize:
            filtered = _normalize_audio(filtered, target_peak=0.9)

        return filtered

