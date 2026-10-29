"""
HTTP REST API для сервиса предобработки аудио и детекции голосовой активности (Preprocess + VAD) на базе FastAPI.
Предоставляет тонкий HTTP-адаптер поверх единого конвейера AudioPreprocessVADPipeline.
"""

import base64
import io
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import List, Literal, Optional, Set, Union

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
import soundfile as sf
import yaml

try:
    from .pipeline import (
        AudioPipelineConfig,
        AudioPipelineResult,
        AudioPreprocessVADPipeline,
        get_audio_pipeline,
        remap_transcription_result,
    )
except (ImportError, ValueError):
    from audio_preprocessing.pipeline import (
        AudioPipelineConfig,
        AudioPipelineResult,
        AudioPreprocessVADPipeline,
        get_audio_pipeline,
        remap_transcription_result,
    )

try:
    from stt.interfaces import TranscriptionResult, TranscriptionSegment
except (ImportError, ValueError):
    from ..stt.interfaces import TranscriptionResult, TranscriptionSegment

logger = logging.getLogger("AudioPreprocessing.API")

ALLOWED_AUDIO_EXTENSIONS: Set[str] = {
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".flac",
    ".webm",
}


# --- Pydantic Схемы API ---


class PipelineHealthResponse(BaseModel):
    """Схема ответа проверки состояния сервиса и активной конфигурации конвейера."""

    status: Literal["ok"] = "ok"
    converter: str = Field(
        description="Активный адаптер конвертации аудио",
        examples=["torchaudio"],
    )
    denoiser: str = Field(
        description="Активный адаптер шумоподавления (или 'none')",
        examples=["stat_spectral"],
    )
    vad: str = Field(
        description="Активный адаптер детекции голоса (или 'none')",
        examples=["silero"],
    )
    target_sr: int = Field(
        description="Целевая частота дискретизации (Гц)",
        examples=[16000],
    )


class SpeechSegmentDTO(BaseModel):
    """Временной интервал обнаруженной речи относительно исходной записи."""

    start: float = Field(
        description="Начало речевого интервала в исходном файле (сек)",
        examples=[1.762],
    )
    end: float = Field(
        description="Конец речевого интервала в исходном файле (сек)",
        examples=[2.334],
    )


class PreprocessResponse(BaseModel):
    """Схема ответа предобработки и VAD аудиофайла."""

    sample_rate: int = Field(
        description="Частота дискретизации выходного потока (Гц)",
        examples=[16000],
    )
    original_duration: float = Field(
        description="Длительность исходной аудиозаписи (сек)",
        examples=[35.07],
    )
    speech_duration: float = Field(
        description="Суммарная длительность чистой речи после VAD (сек)",
        examples=[28.74],
    )
    retention_pct: float = Field(
        description="Процент сохраненного аудиопотока после удаления тишины (0..100%)",
        examples=[81.95],
    )
    segments_count: int = Field(
        description="Количество обнаруженных речевых сегментов",
        examples=[8],
    )
    speech_segments: List[SpeechSegmentDTO] = Field(
        description="Список временных границ речи относительно исходного файла",
    )
    output_wav_path: Optional[str] = Field(
        default=None,
        description="Путь к сохраненному WAV-файлу с чистой речью (если был указан в запросе)",
        examples=["/data/processed/call_speech_only.wav"],
    )
    audio_wav_base64: Optional[str] = Field(
        default=None,
        description="Очищенное речевое аудио в формате WAV (16kHz PCM_16), закодированное в Base64",
        examples=[None],
    )


class PreprocessByPathRequest(BaseModel):
    """Схема запроса предобработки по локальному пути (Shared Volume)."""

    file_path: str = Field(
        description="Путь к исходному аудиофайлу в файловой системе / общем томе",
        examples=["/data/calls/input_test_call.mp3"],
    )
    output_wav_path: Optional[str] = Field(
        default=None,
        description="Путь для сохранения очищенного речевого аудио (16kHz Mono PCM_16 WAV)",
        examples=["/data/processed/call_speech_only.wav"],
    )
    include_audio_base64: bool = Field(
        default=False,
        description="Включить ли очищенное аудио в виде строки Base64 в JSON-ответ",
    )


class RemapTimestampsRequest(BaseModel):
    """Схема запроса пересчета таймкодов транскрибации на шкалу исходного файла."""

    transcription: TranscriptionResult = Field(
        description="Исходный результат транскрибации модели Whisper",
    )
    speech_segments: List[SpeechSegmentDTO] = Field(
        description="Сегменты речи от модуля VAD относительно исходного файла",
    )
    original_duration: Optional[float] = Field(
        default=None,
        description="Длительность исходного аудиофайла в секундах",
        examples=[35.07],
    )


class ErrorResponse(BaseModel):
    """Схема стандартного сообщения об ошибке."""

    detail: str = Field(
        description="Описание причины ошибки",
        examples=["Аудиофайл не найден: /data/calls/missing.mp3"],
    )


# --- Управление зависимостями (Dependency Injection) ---

_pipeline_singleton: Optional[AudioPreprocessVADPipeline] = None


def get_pipeline_service() -> AudioPreprocessVADPipeline:
    """
    Провайдер зависимости экземпляра единого конвейера AudioPreprocessVADPipeline (Singleton с lazy-инициализацией).
    Считывает настройки из переменных окружения:
      - AUDIO_PREP_CONVERTER (default: 'torchaudio')
      - AUDIO_PREP_DENOISER (default: 'stat_spectral')
      - AUDIO_PREP_VAD (default: 'silero')
      - AUDIO_PREP_TARGET_SR (default: 16000)
    Может быть переопределен в тестах через app.dependency_overrides[get_pipeline_service].
    """
    global _pipeline_singleton
    if _pipeline_singleton is None:
        converter = os.getenv("AUDIO_PREP_CONVERTER", "torchaudio")
        denoiser = os.getenv("AUDIO_PREP_DENOISER", "stat_spectral")
        vad = os.getenv("AUDIO_PREP_VAD", "silero")
        target_sr_str = os.getenv("AUDIO_PREP_TARGET_SR", "16000")
        try:
            target_sr = int(target_sr_str)
        except ValueError:
            target_sr = 16000

        logger.info(
            "Инициализация AudioPreprocessVADPipeline синглтона: converter=%s, denoiser=%s, vad=%s, target_sr=%d",
            converter,
            denoiser,
            vad,
            target_sr,
        )

        config = AudioPipelineConfig(
            converter=converter,
            denoiser=denoiser if denoiser != "none" else None,
            vad=vad if vad != "none" else None,
            target_sr=target_sr,
        )
        _pipeline_singleton = get_audio_pipeline(config=config)

    return _pipeline_singleton


def reset_pipeline_service() -> None:
    """Сбрасывает синглтон пайплайна (для тестов с разными конфигурациями окружения)."""
    global _pipeline_singleton
    _pipeline_singleton = None


# --- Инициализация FastAPI приложения ---

tags_metadata = [
    {
        "name": "Preprocessing & VAD",
        "description": "Очистка аудио, детекция речи (VAD) и маппинг таймкодов",
    },
    {
        "name": "System",
        "description": "Мониторинг состояния сервиса и активных стратегий конвейера",
    },
]

app = FastAPI(
    title="SaaS Voice Analysis — Audio Preprocessing & VAD Microservice API",
    description=(
        "Внешний HTTP-интерфейс единого модуля предобработки аудио и детекции голосовой активности (Preprocess + VAD).\n"
        "Выполняет конвертацию медиафайлов в 16 kHz Mono float32, спектральное шумоподавление,\n"
        "вырезание пауз/тишины через VAD и пересчет таймкодов транскрибации на исходный хронометраж звонка.\n"
    ),
    version="1.0.0",
    contact={"name": "SaaS-voice-analysis Team"},
    openapi_tags=tags_metadata,
    servers=[
        {
            "url": "http://localhost:8002",
            "description": "Локальный сервер разработки / Docker-контейнер Preprocess + VAD",
        }
    ],
)
app.openapi_version = "3.0.3"


# --- Эндпоинты API ---


@app.get(
    "/api/v1/health",
    tags=["System"],
    summary="Проверка состояния сервиса и активной конфигурации конвейера",
    operation_id="health_check",
    response_model=PipelineHealthResponse,
    responses={
        200: {
            "description": "Сервис активен, адаптеры конвертации, шумоподавления и VAD готовы к работе",
            "model": PipelineHealthResponse,
        }
    },
)
def health_check(
    service: AudioPreprocessVADPipeline = Depends(get_pipeline_service),
) -> PipelineHealthResponse:
    """
    Возвращает конфигурацию активного пайплайна (converter, denoiser, vad, target_sr).
    """
    converter_name = getattr(service.converter, "name", "unknown")
    denoiser_name = getattr(service.denoiser, "name", "none") if service.denoiser else "none"
    vad_name = getattr(service.vad, "name", "none") if service.vad else "none"
    target_sr = service.config.target_sr

    return PipelineHealthResponse(
        status="ok",
        converter=str(converter_name),
        denoiser=str(denoiser_name),
        vad=str(vad_name),
        target_sr=int(target_sr),
    )


@app.post(
    "/api/v1/preprocess",
    tags=["Preprocessing & VAD"],
    summary="Предобработка и VAD загруженного аудиофайла",
    description=(
        "Принимает сырой аудиофайл через `multipart/form-data`, прогоняет через цепочку\n"
        "`Converter -> Denoiser -> VAD` в оперативной памяти и возвращает временные границы\n"
        "речевых сегментов, метрики удержания речи и (опционально) очищенное аудио в формате WAV Base64.\n"
    ),
    operation_id="preprocess_file",
    response_model=PreprocessResponse,
    responses={
        200: {
            "description": "Аудиозапись успешно обработана",
            "model": PreprocessResponse,
        },
        400: {
            "description": "Неподдерживаемый формат файла или передан пустой аудиофайл",
            "model": ErrorResponse,
        },
        422: {
            "description": "Ошибка валидации входных параметров",
            "model": ErrorResponse,
        },
        500: {
            "description": "Внутренняя ошибка при обработке аудиопотока",
            "model": ErrorResponse,
        },
    },
)
def preprocess_file(
    file: UploadFile = File(
        ...,
        description="Входной аудиофайл звонка (.mp3, .wav, .ogg, .m4a, .flac, .webm)",
    ),
    include_audio_base64: bool = Form(
        False,
        description="Вернуть ли склеенный речевой поток (16kHz Mono PCM_16 WAV) в поле audio_wav_base64",
    ),
    service: AudioPreprocessVADPipeline = Depends(get_pipeline_service),
) -> PreprocessResponse:
    """
    Принимает аудиофайл через multipart/form-data, сохраняет его во временный файл,
    выполняет цепочку обработки Converter -> Denoiser -> VAD и удаляет временный файл в блоке finally.
    """
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Неподдерживаемый формат аудиофайла: '{suffix or filename}'. "
                f"Разрешены: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}"
            ),
        )

    tmp_path: Optional[Path] = None
    try:
        file.file.seek(0)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_path = Path(tmp_file.name)
            shutil.copyfileobj(file.file, tmp_file)
            file_size = tmp_file.tell()

        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="Передан пустой аудиофайл",
            )

        result = service.process_detailed(tmp_path)

        audio_b64: Optional[str] = None
        if include_audio_base64:
            buf = io.BytesIO()
            sf.write(
                buf,
                result.speech_only_audio,
                result.sample_rate,
                format="WAV",
                subtype="PCM_16",
            )
            audio_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        segments_dto = [
            SpeechSegmentDTO(start=seg["start"], end=seg["end"])
            for seg in result.speech_segments
        ]

        return PreprocessResponse(
            sample_rate=result.sample_rate,
            original_duration=result.original_duration,
            speech_duration=result.speech_duration,
            retention_pct=result.retention_pct,
            segments_count=len(segments_dto),
            speech_segments=segments_dto,
            output_wav_path=None,
            audio_wav_base64=audio_b64,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Внутренняя ошибка при обработке аудиопотока: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка при обработке аудиопотока: {e}",
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@app.post(
    "/api/v1/preprocess/by-path",
    tags=["Preprocessing & VAD"],
    summary="Предобработка и VAD аудиофайла по локальному пути (Shared Volume)",
    description=(
        "Используется при взаимодействии контейнеров через общий том (Shared Volume).\n"
        "Позволяет прочитать исходный звонок по `file_path` и сохранить очищенный речевой\n"
        "поток `speech_only_audio` в `output_wav_path` для последующей передачи в сервис STT.\n"
    ),
    operation_id="preprocess_by_path",
    response_model=PreprocessResponse,
    responses={
        200: {
            "description": "Аудиозапись успешно обработана",
            "model": PreprocessResponse,
        },
        404: {
            "description": "Исходный аудиофайл не найден по указанному пути",
            "model": ErrorResponse,
        },
        422: {
            "description": "Ошибка валидации запроса",
            "model": ErrorResponse,
        },
        500: {
            "description": "Внутренняя ошибка сервиса",
            "model": ErrorResponse,
        },
    },
)
def preprocess_by_path(
    request: PreprocessByPathRequest,
    service: AudioPreprocessVADPipeline = Depends(get_pipeline_service),
) -> PreprocessResponse:
    """
    Предобрабатывает аудиофайл по локальному пути или общему тому (Shared Volume).
    Опционально сохраняет речевой поток speech_only_audio в output_wav_path и/или возвращает в base64.
    """
    file_path = Path(request.file_path)
    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Исходный аудиофайл не найден: {request.file_path}",
        )

    try:
        result = service.process_detailed(file_path)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Ошибка при обработке файла по пути: %s", request.file_path)
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервиса: {e}",
        )

    saved_wav_path: Optional[str] = None
    if request.output_wav_path:
        out_path = Path(request.output_wav_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(
            str(out_path),
            result.speech_only_audio,
            result.sample_rate,
            format="WAV",
            subtype="PCM_16",
        )
        saved_wav_path = str(out_path)

    audio_b64: Optional[str] = None
    if request.include_audio_base64:
        buf = io.BytesIO()
        sf.write(
            buf,
            result.speech_only_audio,
            result.sample_rate,
            format="WAV",
            subtype="PCM_16",
        )
        audio_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    segments_dto = [
        SpeechSegmentDTO(start=seg["start"], end=seg["end"])
        for seg in result.speech_segments
    ]

    return PreprocessResponse(
        sample_rate=result.sample_rate,
        original_duration=result.original_duration,
        speech_duration=result.speech_duration,
        retention_pct=result.retention_pct,
        segments_count=len(segments_dto),
        speech_segments=segments_dto,
        output_wav_path=saved_wav_path,
        audio_wav_base64=audio_b64,
    )


@app.post(
    "/api/v1/remap-timestamps",
    tags=["Preprocessing & VAD"],
    summary="Восстановление таймкодов транскрибации на шкалу исходного звонка",
    description=(
        "Принимает результат транскрибации (`TranscriptionResult`), полученный на склеенном\n"
        "после VAD аудио, и список интервалов `speech_segments`. Возвращает новый `TranscriptionResult`,\n"
        "в котором таймкоды `start` и `end` каждого сегмента пересчитаны относительно оригинальной аудиозаписи.\n"
    ),
    operation_id="remap_timestamps",
    response_model=TranscriptionResult,
    responses={
        200: {
            "description": "Таймкоды сегментов успешно пересчитаны",
            "model": TranscriptionResult,
        },
        422: {
            "description": "Ошибка валидации входных данных",
            "model": ErrorResponse,
        },
    },
)
def remap_timestamps(
    request: RemapTimestampsRequest,
) -> TranscriptionResult:
    """
    Принимает результат транскрибации (TranscriptionResult) и сегменты речи VAD,
    возвращая TranscriptionResult с таймкодами исходного звонка.
    """
    segments_dicts = [
        {"start": seg.start, "end": seg.end}
        for seg in request.speech_segments
    ]
    return remap_transcription_result(
        result=request.transcription,
        speech_segments=segments_dicts,
        original_duration=request.original_duration,
    )


def export_openapi_yaml(output_path: Union[str, Path] = "audio_preprocessing/openapi.yaml") -> None:
    """
    Экспортирует актуальную OpenAPI спецификацию приложения в YAML-файл.
    """
    path = Path(output_path)
    schema = app.openapi()
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(schema, f, allow_unicode=True, sort_keys=False)
    logger.info("OpenAPI спецификация сохранена в %s", path)


if __name__ == "__main__":
    export_openapi_yaml()
