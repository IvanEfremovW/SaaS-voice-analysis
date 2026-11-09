"""
Адаптеры детекции голосовой активности (VAD) (Issue #6).
Реализация трех независимых стратегий:
1. SileroVADAdapter (ONNX runtime inference)
2. WebRTCVADAdapter (16-bit PCM, фреймы 30 мс, окно сглаживания hangover 300 мс)
3. EnergyVADAdapter (librosa.effects.split по порогу громкости top_db=25)
"""

import logging
from typing import Dict, List, Tuple
import numpy as np

try:
    from .interfaces import BaseVAD
except (ImportError, ValueError):
    from vad.interfaces import BaseVAD

logger = logging.getLogger(__name__)


class SileroVADAdapter(BaseVAD):
    """
    Детектор речи на базе нейросети Silero VAD (ONNX runtime).
    Высокая точность отделения речи от сложного шума, стабильная работа на CPU.
    """

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._model = None
        self._init_model()

    def _init_model(self):
        try:
            from silero_vad import load_silero_vad
            self._model = load_silero_vad(onnx=True)
            logger.debug("Silero VAD (ONNX) инициализирован.")
        except Exception as exc:
            logger.error("Не удалось загрузить Silero VAD ONNX: %s", exc)
            raise

    @property
    def name(self) -> str:
        return "silero"

    def process(self, audio: np.ndarray, sr: int = 16000) -> Tuple[np.ndarray, List[Dict[str, float]]]:
        import torch
        from silero_vad import get_speech_timestamps

        if len(audio) == 0:
            return np.empty((0,), dtype=np.float32), []

        tensor_audio = torch.from_numpy(audio.astype(np.float32))
        raw_segments = get_speech_timestamps(
            tensor_audio,
            self._model,
            threshold=self.threshold,
            sampling_rate=sr
        )

        if not raw_segments:
            logger.warning("Silero VAD не обнаружил речевых сегментов. Возвращается исходный сигнал.")
            return audio, [{"start": 0.0, "end": round(len(audio) / sr, 3)}]

        speech_chunks = []
        segments = []
        for seg in raw_segments:
            s_idx = seg["start"]
            e_idx = seg["end"]
            speech_chunks.append(audio[s_idx:e_idx])
            segments.append({
                "start": round(s_idx / sr, 3),
                "end": round(e_idx / sr, 3)
            })

        concatenated = np.concatenate(speech_chunks).astype(np.float32)
        return concatenated, segments


class WebRTCVADAdapter(BaseVAD):
    """
    Детектор речи на базе WebRTC VAD.
    Анализирует сигнал короткими 30-миллисекундными фреймами (16-bit PCM).
    Использует адаптивное окно сглаживания (hangover 300 мс), чтобы не обрезать
    окончания слов и короткие межслоговые паузы.
    """

    def __init__(self, mode: int = 2, frame_duration_ms: int = 30, hangover_ms: int = 300):
        """
        :param mode: Агрессивность VAD от 0 (наименее строгий) до 3 (наиболее строгий).
        :param frame_duration_ms: Длительность одного кадра (10, 20 или 30 мс).
        :param hangover_ms: Время удержания статуса речи после обнаружения паузы.
        """
        import webrtcvad

        self.mode = mode
        self.frame_duration_ms = frame_duration_ms
        self.hangover_ms = hangover_ms
        self.vad = webrtcvad.Vad(mode)

    @property
    def name(self) -> str:
        return "webrtc"

    def process(self, audio: np.ndarray, sr: int = 16000) -> Tuple[np.ndarray, List[Dict[str, float]]]:
        if len(audio) == 0:
            return np.empty((0,), dtype=np.float32), []

        # WebRTC VAD строго требует 8000, 16000, 32000 или 48000 Гц и 16-битный PCM
        samples_per_frame = int(sr * self.frame_duration_ms / 1000)
        hangover_frames = int(self.hangover_ms / self.frame_duration_ms)

        pcm16 = np.clip(audio * 32767.0, -32768.0, 32767.0).astype(np.int16)

        total_frames = len(pcm16) // samples_per_frame
        if total_frames == 0:
            return audio, [{"start": 0.0, "end": round(len(audio) / sr, 3)}]

        # Покадровая классификация
        frame_is_speech = []
        for i in range(total_frames):
            start = i * samples_per_frame
            end = start + samples_per_frame
            frame_bytes = pcm16[start:end].tobytes()
            is_speech = self.vad.is_speech(frame_bytes, sr)
            frame_is_speech.append(is_speech)

        # Сглаживание через hangover (удержание состояния речи)
        smoothed = []
        silence_count = 0
        in_speech = False

        for is_speech in frame_is_speech:
            if is_speech:
                in_speech = True
                silence_count = 0
                smoothed.append(True)
            else:
                if in_speech:
                    silence_count += 1
                    if silence_count <= hangover_frames:
                        smoothed.append(True)
                    else:
                        in_speech = False
                        smoothed.append(False)
                else:
                    smoothed.append(False)

        # Выделение непрерывных интервалов речи
        intervals = []
        seg_start = None
        for i, speech in enumerate(smoothed):
            if speech and seg_start is None:
                seg_start = i * samples_per_frame
            elif not speech and seg_start is not None:
                intervals.append((seg_start, i * samples_per_frame))
                seg_start = None
        if seg_start is not None:
            intervals.append((seg_start, total_frames * samples_per_frame))

        if not intervals:
            logger.warning("WebRTC VAD не выделил интервалов речи. Возвращается исходный сигнал.")
            return audio, [{"start": 0.0, "end": round(len(audio) / sr, 3)}]

        speech_chunks = [audio[s:e] for s, e in intervals]
        segments = [
            {"start": round(s / sr, 3), "end": round(e / sr, 3)}
            for s, e in intervals
        ]

        concatenated = np.concatenate(speech_chunks).astype(np.float32)
        return concatenated, segments


class EnergyVADAdapter(BaseVAD):
    """
    Энергетический детектор активности на базе порога громкости (librosa.effects.split).
    Простой, быстрый эвристический подход, разделяющий сигнал по децибельному уровню от пика.
    """

    def __init__(self, top_db: float = 10.0, frame_length: int = 2048, hop_length: int = 256):
        self.top_db = top_db
        self.frame_length = frame_length
        self.hop_length = hop_length

    @property
    def name(self) -> str:
        return "energy"

    def process(self, audio: np.ndarray, sr: int = 16000) -> Tuple[np.ndarray, List[Dict[str, float]]]:
        import librosa

        if len(audio) == 0:
            return np.empty((0,), dtype=np.float32), []

        # Разделение по энергетическому порогу top_db
        intervals = librosa.effects.split(
            y=audio,
            top_db=self.top_db,
            frame_length=self.frame_length,
            hop_length=self.hop_length
        )

        if len(intervals) == 0:
            logger.warning("Energy VAD не обнаружил интервалов громче порога top_db=%s. Возвращается оригинал.", self.top_db)
            return audio, [{"start": 0.0, "end": round(len(audio) / sr, 3)}]

        speech_chunks = [audio[s:e] for s, e in intervals]
        segments = [
            {"start": round(s / sr, 3), "end": round(e / sr, 3)}
            for s, e in intervals
        ]

        concatenated = np.concatenate(speech_chunks).astype(np.float32)
        return concatenated, segments
