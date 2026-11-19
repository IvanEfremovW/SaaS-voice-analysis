"""
Адаптер транскрибации речи на базе faster-whisper (CTranslate2).
Соблюдение паттерна Strategy/Adapter, архитектурных стандартов AGENTS.md
и нативная поддержка graceful fallback на CPU без зависимости от PyTorch.
"""

import logging
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, List, Optional, Union
import ctranslate2
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio
from faster_whisper.transcribe import Segment
from faster_whisper.vad import get_speech_timestamps
import numpy as np

from .config import TranscriberConfig
from .coverage import RETRY_CONTEXT, retry_intervals, uncovered_intervals
from .interfaces import (
    BaseTranscriber,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
    build_utterances,
)

logger = logging.getLogger("STT.FasterWhisper")
SAMPLE_RATE = 16000


def _convert_segments(
    source: Iterable[Segment], duration: float, offset: float = 0.0
) -> list[TranscriptionSegment]:
    def timestamp(seconds: float) -> float:
        return round(offset + min(max(seconds, 0.0), duration), 3)

    return [
        TranscriptionSegment(
            id=segment.id,
            start=timestamp(segment.start),
            end=timestamp(max(segment.start, segment.end)),
            text=segment.text.strip(),
            avg_logprob=segment.avg_logprob,
            no_speech_prob=segment.no_speech_prob,
            words=[
                TranscriptionWord(
                    text=word.word.strip(),
                    start=timestamp(word.start),
                    end=timestamp(max(word.start, word.end)),
                    probability=word.probability,
                )
                for word in (segment.words or [])
                if word.word.strip()
            ],
        )
        for segment in source
    ]


def _word_key(word: TranscriptionWord) -> str:
    return word.text.casefold().strip('.,!?…:;«»“”\"()')


class TranscriberDeviceError(RuntimeError):
    """Запрошенное устройство недоступно."""


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
        target_device = self.config.device
        cuda_count = ctranslate2.get_cuda_device_count() if target_device != "cpu" else 0
        compute_type = self.config.compute_type
        device_index = self.config.device_index

        if target_device == "cuda":
            if cuda_count == 0:
                if not self.config.allow_cuda_fallback:
                    raise TranscriberDeviceError("CUDA недоступна на воркере")
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

    def _recover_speech(
        self,
        audio: np.ndarray,
        segments: list[TranscriptionSegment],
        options: dict[str, Any],
    ) -> list[TranscriptionSegment]:
        gaps = list(uncovered_intervals(segments, len(audio) / SAMPLE_RATE))
        if not gaps:
            return []
        try:
            speech = [
                (chunk["start"] / SAMPLE_RATE, chunk["end"] / SAMPLE_RATE)
                for chunk in get_speech_timestamps(audio)
            ]
        except RuntimeError:
            logger.warning("Детектор речи недоступен для повторного прохода", exc_info=True)
            return []
        targets = retry_intervals(gaps, speech)
        if not targets:
            return []

        known_words: dict[str, list[TranscriptionWord]] = defaultdict(list)
        for segment in segments:
            for word in segment.words:
                known_words[_word_key(word)].append(word)

        retry_options = {**options, "vad_filter": False, "condition_on_previous_text": False, "prefix": None}
        recovered: list[TranscriptionSegment] = []
        for start, end in targets:
            clip_start = max(0, round((start - RETRY_CONTEXT) * SAMPLE_RATE))
            clip_end = min(len(audio), round((end + RETRY_CONTEXT) * SAMPLE_RATE))
            try:
                retry, _ = self.model.transcribe(audio[clip_start:clip_end], **retry_options)
                retry_segments = _convert_segments(
                    retry, duration=(clip_end - clip_start) / SAMPLE_RATE, offset=clip_start / SAMPLE_RATE
                )
            except RuntimeError:
                logger.warning("Повторное распознавание прервано, сохраняем полученные сегменты", exc_info=True)
                break

            for candidate in retry_segments:
                if candidate.avg_logprob < -1.0:
                    continue
                words: list[TranscriptionWord] = []
                for word in candidate.words:
                    midpoint = (word.start + word.end) / 2
                    if not start <= midpoint < end:
                        continue
                    seen = known_words[_word_key(word)]
                    if any(word.start < other.end and other.start < word.end for other in seen):
                        continue
                    seen.append(word)
                    words.append(word)
                if words:
                    recovered.append(candidate.model_copy(update={
                        "start": words[0].start,
                        "end": words[-1].end,
                        "text": " ".join(word.text for word in words),
                        "words": words,
                    }))

        logger.info("Повторное распознавание: %d участков, %d добавленных сегментов", len(targets), len(recovered))
        return recovered

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

        word_timestamps = kwargs.pop("word_timestamps", self.config.word_timestamps)
        recover = (
            kwargs.pop("recover_missing_speech", self.config.recover_missing_speech)
            and word_timestamps
            and kwargs.get("clip_timestamps", "0") == "0"
        )
        if recover and isinstance(audio_input, str):
            audio_input = decode_audio(audio_input, sampling_rate=SAMPLE_RATE)

        options = dict(
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=initial_prompt,
            word_timestamps=word_timestamps,
            **kwargs,
        )
        segments_generator, info = self.model.transcribe(audio_input, **options)
        segment_duration = info.duration if info.duration is not None else float("inf")
        segments = _convert_segments(segments_generator, duration=segment_duration)
        recovered = []
        if recover and isinstance(audio_input, np.ndarray) and audio_input.size:
            recovered = self._recover_speech(audio_input, segments, {**options, "language": info.language})

        if recovered:
            segments = sorted(segments + recovered, key=lambda segment: segment.start)
            segments = [segment.model_copy(update={"id": index}) for index, segment in enumerate(segments, 1)]
            full_text = " ".join(utterance.text for utterance in build_utterances(segments))
        else:
            full_text = " ".join(segment.text for segment in segments if segment.text)

        duration: float
        if info.duration is not None and info.duration > 0:
            duration = float(info.duration)
        elif isinstance(audio, np.ndarray):
            duration = len(audio_input) / SAMPLE_RATE
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
