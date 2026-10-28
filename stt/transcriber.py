"""
Адаптер транскрибации речи на базе faster-whisper (CTranslate2).
Соблюдение паттерна Strategy/Adapter, архитектурных стандартов AGENTS.md
и нативная поддержка graceful fallback на CPU без зависимости от PyTorch.
"""

import logging
from pathlib import Path
from typing import Any, List, Optional, Union
import ctranslate2
from faster_whisper import WhisperModel
import numpy as np

from .config import TranscriberConfig
from .interfaces import BaseTranscriber, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger("STT.FasterWhisper")


class FasterWhisperTranscriber(BaseTranscriber):
    """
    Реализация транскрибатора на базе библиотеки faster-whisper.
    """

    def __init__(self, config: Optional[TranscriberConfig] = None) -> None:
        """
        Инициализирует модель faster-whisper с проверкой доступности GPU
        и автоматическим fallback на CPU.
        """
        self.config = config or TranscriberConfig()

        # Нативная проверка CUDA через CTranslate2 без зависимости от PyTorch
        cuda_count = ctranslate2.get_cuda_device_count()
        target_device = self.config.device
        compute_type = self.config.compute_type
        device_index = self.config.device_index

        if target_device == "cuda":
            if cuda_count == 0:
                logger.warning(
                    "Запрошено устройство 'cuda', но CUDA-устройства не обнаружены "
                    "(ctranslate2.get_cuda_device_count() == 0). "
                    "Выполняется автоматический fallback на 'cpu' с compute_type='int8'."
                )
                target_device = "cpu"
                compute_type = "int8"
            elif device_index >= cuda_count:
                logger.warning(
                    "Указанный device_index=%d превышает количество доступных GPU (%d). "
                    "Используется device_index=0.",
                    device_index,
                    cuda_count,
                )
                device_index = 0
        elif target_device == "auto":
            if cuda_count > 0:
                target_device = "cuda"
            else:
                target_device = "cpu"
                if compute_type == "float16":
                    compute_type = "int8"

        # Защита от запуска float16 на CPU (CTranslate2 требует int8 или float32 на CPU)
        if target_device == "cpu" and compute_type == "float16":
            logger.warning(
                "compute_type='float16' не поддерживается на CPU в CTranslate2. "
                "Автоматическое переключение на compute_type='int8'."
            )
            compute_type = "int8"

        self._actual_device = target_device
        self._actual_compute_type = compute_type
        self._actual_device_index = device_index

        logger.info(
            "Загрузка модели Whisper (размер='%s', device='%s', compute_type='%s', device_index=%d)",
            self.config.model_size,
            self._actual_device,
            self._actual_compute_type,
            self._actual_device_index,
        )

        self.model = WhisperModel(
            model_size_or_path=self.config.model_size,
            device=self._actual_device,
            device_index=self._actual_device_index,
            compute_type=self._actual_compute_type,
        )

    @property
    def name(self) -> str:
        return f"faster-whisper-{self.config.model_size}"

    @property
    def actual_device(self) -> str:
        return self._actual_device

    @property
    def actual_compute_type(self) -> str:
        return self._actual_compute_type

    def transcribe(
        self,
        audio: Union[str, Path, np.ndarray],
        **kwargs: Any,
    ) -> TranscriptionResult:
        """
        Транскрибирует аудиозапись.

        :param audio: Путь к файлу (str, Path) или 1D np.ndarray (float32, 16kHz).
        :param kwargs: Переопределение параметров (language, beam_size, vad_filter и др.).
        :return: Валидированный TranscriptionResult.
        """
        # 1. Валидация и нормализация входных аудиоданных
        audio_input: Union[str, np.ndarray]

        if isinstance(audio, Path):
            resolved_path = audio.resolve()
            if not resolved_path.is_file():
                raise FileNotFoundError(f"Аудиофайл не найден: {resolved_path}")
            audio_input = str(resolved_path)

        elif isinstance(audio, str):
            path_obj = Path(audio).resolve()
            if not path_obj.is_file():
                raise FileNotFoundError(f"Аудиофайл не найден: {audio}")
            audio_input = str(path_obj)

        elif isinstance(audio, np.ndarray):
            if audio.size == 0:
                logger.warning("Передан пустой массив аудио.")
                return TranscriptionResult(
                    text="",
                    language=self.config.language or "unknown",
                    language_probability=0.0,
                    duration=0.0,
                    segments=[],
                )

            # Приведение многоканального аудио к 1D моно
            if audio.ndim == 2:
                if audio.shape[0] in (1, 2) and audio.shape[1] > audio.shape[0]:
                    audio = np.mean(audio, axis=0)
                elif audio.shape[1] in (1, 2) and audio.shape[0] > audio.shape[1]:
                    audio = np.mean(audio, axis=1)
                else:
                    audio = audio.flatten()
            elif audio.ndim > 2:
                audio = audio.flatten()

            # Приведение к float32 с нормализацией, если целочисленный тип
            if np.issubdtype(audio.dtype, np.integer):
                max_val = float(np.iinfo(audio.dtype).max)
                audio_input = (audio / max_val).astype(np.float32)
            elif audio.dtype != np.float32:
                audio_input = audio.astype(np.float32)
            else:
                audio_input = audio

        else:
            raise TypeError(
                f"Неподдерживаемый тип аудио: {type(audio)}. "
                "Ожидается str, pathlib.Path или numpy.ndarray."
            )

        # 2. Определение параметров инференса
        language = kwargs.pop("language", self.config.language)
        beam_size = kwargs.pop("beam_size", self.config.beam_size)
        vad_filter = kwargs.pop("vad_filter", self.config.vad_filter)
        condition_on_previous_text = kwargs.pop(
            "condition_on_previous_text", self.config.condition_on_previous_text
        )
        initial_prompt = kwargs.pop("initial_prompt", self.config.initial_prompt)

        # 3. Инференс faster-whisper
        segments_generator, info = self.model.transcribe(
            audio_input,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=initial_prompt,
            **kwargs,
        )

        # 4. Сборка сегментов
        segments: List[TranscriptionSegment] = []
        for seg in segments_generator:
            clean_text = seg.text.strip()
            segments.append(
                TranscriptionSegment(
                    id=int(seg.id),
                    start=round(float(seg.start), 3),
                    end=round(float(seg.end), 3),
                    text=clean_text,
                    avg_logprob=float(seg.avg_logprob),
                    no_speech_prob=float(seg.no_speech_prob),
                )
            )

        # 5. Сборка полного текста и расчет длительности
        full_text = " ".join([s.text for s in segments if s.text]).strip()

        duration: float
        if info.duration is not None and info.duration > 0:
            duration = float(info.duration)
        elif isinstance(audio, np.ndarray):
            duration = float(len(audio_input) / 16000.0)
        elif segments:
            duration = float(segments[-1].end)
        else:
            duration = 0.0

        lang_prob = (
            round(float(info.language_probability), 3)
            if info.language_probability is not None
            else 0.0
        )

        return TranscriptionResult(
            text=full_text,
            language=str(info.language or language or "unknown"),
            language_probability=lang_prob,
            duration=round(duration, 3),
            segments=segments,
        )
