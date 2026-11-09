"""
Главный конвейер-оркестратор обработки звонков (CallProcessingPipeline).
Управляет потоком данных между сервисами загрузки, предобработки и транскрибации через композицию (Dependency Injection).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np

from stt.interfaces import TranscriptionResult, TranscriptionSegment
from .interfaces import BaseAudioLoader

logger = logging.getLogger("Orchestrator.Pipeline")


def remap_time_to_original(
    compact_time: float,
    speech_segments: List[Dict[str, float]],
    is_end: bool = False,
) -> float:
    """
    Пересчитывает время (в секундах) внутри склеенного speech_only_audio
    обратно на реальную временную шкалу исходного звонка по списку speech_segments.

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


def remap_transcription_result(
    result: TranscriptionResult,
    speech_segments: List[Dict[str, float]],
    original_duration: Optional[float] = None,
) -> TranscriptionResult:
    """
    Возвращает новый объект TranscriptionResult с пересчитанными start / end метками
    у всех сегментов на основе исходной шкалы времени звонка до VAD.

    :param result: Исходный результат транскрибации модели Whisper.
    :param speech_segments: Список речевых сегментов VAD [{'start': float, 'end': float}].
    :param original_duration: Длительность исходного аудиофайла в секундах.
    :return: Валидированный TranscriptionResult с таймкодами исходного файла.
    """
    new_segments: List[TranscriptionSegment] = []
    for seg in result.segments:
        new_start = remap_time_to_original(seg.start, speech_segments, is_end=False)
        new_end = remap_time_to_original(seg.end, speech_segments, is_end=True)
        if new_end < new_start:
            new_end = new_start

        new_segments.append(
            TranscriptionSegment(
                id=seg.id,
                start=new_start,
                end=new_end,
                text=seg.text,
                avg_logprob=seg.avg_logprob,
                no_speech_prob=seg.no_speech_prob,
            )
        )

    if original_duration is not None:
        new_duration = round(float(original_duration), 3)
    elif speech_segments:
        new_duration = round(float(speech_segments[-1]["end"]), 3)
    else:
        new_duration = result.duration

    return TranscriptionResult(
        text=result.text,
        language=result.language,
        language_probability=result.language_probability,
        duration=new_duration,
        segments=new_segments,
    )


class CallProcessingPipeline:
    """
    Внешний оркестратор конвейера обработки телефонных звонков.
    Объединяет загрузку аудио, предобработку/VAD и STT через композицию (Loose Coupling).
    Поддерживает как in-memory адаптеры, так и микросервисы через REST API.
    """

    def __init__(
        self,
        audio_loader: BaseAudioLoader,
        transcriber: Any,
        preprocessor: Optional[Any] = None,
        remap_timestamps: bool = True,
    ) -> None:
        """
        :param audio_loader: Сервис загрузки медиафайлов (BaseAudioLoader).
        :param transcriber: Сервис распознавания речи (BaseTranscriber или RestTranscriberClient).
        :param preprocessor: Сервис предобработки и VAD (AudioPreprocessVADPipeline или RestPreprocessorClient).
                             Если None — предобработка отключена, в STT идет сырое аудио.
        :param remap_timestamps: Пересчитывать ли таймкоды на шкалу исходного файла при включенной предобработке.
        """
        self.audio_loader = audio_loader
        self.transcriber = transcriber
        self.preprocessor = preprocessor
        self.remap_timestamps = remap_timestamps

        logger.info(
            "Инициализирован CallProcessingPipeline: loader=%s, preprocessor=%s, transcriber=%s, remap=%s",
            type(self.audio_loader).__name__,
            type(self.preprocessor).__name__ if self.preprocessor else "None (disabled)",
            type(self.transcriber).__name__,
            self.remap_timestamps,
        )

    def run(
        self,
        call_source: Union[str, Path],
        **transcribe_kwargs: Any,
    ) -> TranscriptionResult:
        """
        Запускает сквозную обработку звонка:
        1. Загрузка аудио через audio_loader.
        2. Если preprocessor задан:
             - Очистка от шума и детекция речи (VAD) -> speech_only_audio + speech_segments.
             - Транскрибация speech_only_audio (модуль STT не знает о препроцессинге).
             - Восстановление таймкодов на исходный хронометраж (если remap_timestamps=True).
        3. Если preprocessor is None:
             - Сырое аудио направляется напрямую в transcriber.

        :param call_source: Путь к файлу звонка или идентификатор в CRM.
        :param transcribe_kwargs: Дополнительные параметры транскрибации (язык, beam_size и т.д.).
        :return: Итоговый TranscriptionResult.
        """
        # 1. Загрузка исходного аудиопотока
        logger.debug("Загрузка аудиозвонка: %s", call_source)
        audio, sr = self.audio_loader.load(call_source)
        orig_duration = round(float(len(audio) / sr), 3) if len(audio) > 0 else 0.0

        # 2. Ветвление: с предобработкой или напрямую
        if self.preprocessor is not None:
            logger.debug(
                "Предобработка включена (%s). Обработка аудио длительностью %.2f сек...",
                type(self.preprocessor).__name__,
                orig_duration,
            )
            if hasattr(self.preprocessor, "process"):
                speech_only_audio, speech_segments = self.preprocessor.process(audio, sr=sr)
            elif callable(self.preprocessor):
                speech_only_audio, speech_segments = self.preprocessor(audio, sr=sr)
            else:
                raise TypeError(
                    f"Препроцессор не поддерживает метод process() или вызов: {type(self.preprocessor)}"
                )

            speech_duration = round(float(len(speech_only_audio) / sr), 3) if len(speech_only_audio) > 0 else 0.0
            logger.debug(
                "Предобработка завершена: чистая речь = %.2f сек (сегментов: %d)",
                speech_duration,
                len(speech_segments),
            )

            # Транскрибатор принимает только аудиофрагменты речи
            logger.debug("Отправка чистой речи в транскрибатор (%s)...", type(self.transcriber).__name__)
            raw_result = self.transcriber.transcribe(speech_only_audio, **transcribe_kwargs)

            # Восстановление временных границ на шкалу исходного звонка
            if self.remap_timestamps and speech_segments:
                logger.debug("Пересчет таймкодов транскрибации на шкалу исходного звонка (%.2f сек)...", orig_duration)
                return remap_transcription_result(
                    result=raw_result,
                    speech_segments=speech_segments,
                    original_duration=orig_duration,
                )
            return raw_result

        # Предобработка выключена — передаем сырое аудио напрямую в STT
        logger.debug(
            "Предобработка выключена. Отправка сырого аудио (%.2f сек) напрямую в %s...",
            orig_duration,
            type(self.transcriber).__name__,
        )
        return self.transcriber.transcribe(audio, **transcribe_kwargs)
