"""
HTTP REST API для сервиса транскрибации речи (STT) на базе FastAPI.
Предоставляет тонкий HTTP-адаптер поверх абстрактного интерфейса BaseTranscriber.
"""

import logging
import os
from pathlib import Path
import shutil
import tempfile
from threading import Lock
from typing import Literal, Optional, Set, Union
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from audio_http import AudioUploadLimit, PyAVInputValidator, require_shared_access, shared_path
from pydantic import BaseModel, Field
import yaml

from .config import DEFAULT_MODEL_SIZE, TranscriberConfig
from .interfaces import BaseTranscriber, TranscriptionResult
from . import get_transcriber

logger = logging.getLogger("STT.API")

ALLOWED_AUDIO_EXTENSIONS: Set[str] = {
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".flac",
    ".webm",
}

# --- Pydantic Схемы API ---


class HealthResponse(BaseModel):
    """Схема ответа проверки состояния сервиса и параметров загруженной модели."""

    status: Literal["ok"] = "ok"
    engine: str = Field(description="Имя активного STT движка/адаптера")
    model_size: str = Field(description="Размер используемой модели Whisper")
    device: str = Field(description="Фактическое вычислительное устройство (cuda/cpu)")
    compute_type: str = Field(description="Фактический тип вычислений/квантования")


class TranscribeByPathRequest(BaseModel):
    """Схема запроса транскрибации по пути к файлу в локальной файловой системе."""

    file_path: str = Field(description="Путь к аудиофайлу в файловой системе или общем томе")
    language: Optional[str] = Field(
        default="ru",
        description="Код языка ISO 639-1 (например, 'ru') или None для автоопределения",
    )
    beam_size: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Размер лучевого поиска (beam search)",
    )
    vad_filter: bool = Field(
        default=False,
        description="Использовать ли встроенный VAD-фильтр пауз",
    )
    condition_on_previous_text: bool = Field(
        default=False,
        description="Защита от зацикливания и повторов на паузах",
    )
    initial_prompt: Optional[str] = Field(
        default=None,
        description="Начальный промпт/глоссарий для повышения точности терминов",
    )


class ErrorResponse(BaseModel):
    """Схема стандартного сообщения об ошибке."""

    detail: str = Field(description="Текстовое описание возникшей ошибки")


# --- Управление зависимостями (Dependency Injection) ---

_stt_singleton: Optional[BaseTranscriber] = None
_service_lock = Lock()


def get_stt_service() -> BaseTranscriber:
    """
    Провайдер зависимости экземпляра транскрибатора (Singleton с lazy-инициализацией).
    Считывает настройки из переменных окружения:
      - STT_ENGINE (default: 'faster-whisper')
      - STT_MODEL_SIZE (default: 'small')
      - STT_DEVICE (default: 'cuda')
      - STT_COMPUTE_TYPE (default: 'float16')
    Может быть переопределен в тестах через app.dependency_overrides[get_stt_service].
    """
    global _stt_singleton
    with _service_lock:
        if _stt_singleton is None:
            engine = os.getenv("STT_ENGINE", "faster-whisper")
            model_size = os.getenv("STT_MODEL_SIZE", DEFAULT_MODEL_SIZE)
            device = os.getenv("STT_DEVICE", "cuda")
            compute_type = os.getenv("STT_COMPUTE_TYPE", "float16")

            logger.info(
                "Инициализация STT синглтона: engine=%s, model_size=%s, device=%s, compute_type=%s",
                engine,
                model_size,
                device,
                compute_type,
            )

            config = TranscriberConfig(
                model_size=model_size,
                device=device,  # type: ignore[arg-type]
                compute_type=compute_type,
            )
            _stt_singleton = get_transcriber(engine=engine, config=config)
    return _stt_singleton


# --- Инициализация FastAPI приложения ---

app = FastAPI(
    title="SaaS Voice Analysis — STT Microservice API",
    description=(
        "Внешний HTTP-интерфейс изолированного модуля транскрибации речи (Speech-to-Text).\n"
        "Принимает аудиодорожку звонка и возвращает структурированный текст с таймкодами сегментов.\n"
    ),
    version="1.0.0",
    servers=[
        {
            "url": "/",
            "description": "Default server / Reverse proxy root",
        }
    ],
)

app.add_middleware(AudioUploadLimit)


# --- Эндпоинты API ---


@app.get(
    "/api/v1/health",
    tags=["System"],
    response_model=HealthResponse,
    summary="Проверка состояния сервиса и загруженной модели",
    responses={
        200: {
            "description": "Сервис активен, модель инициализирована и готова к инференсу",
            "model": HealthResponse,
        }
    },
)
def health_check(
    service: BaseTranscriber = Depends(get_stt_service),
) -> HealthResponse:
    """
    Возвращает текущее состояние транскрибатора (engine, model_size,
    фактический device и compute_type с учетом аппаратного fallback).
    """
    engine_name = service.name
    model_size = getattr(getattr(service, "config", None), "model_size", "unknown")
    actual_device = getattr(
        service,
        "actual_device",
        getattr(getattr(service, "config", None), "device", "unknown"),
    )
    actual_compute_type = getattr(
        service,
        "actual_compute_type",
        getattr(getattr(service, "config", None), "compute_type", "unknown"),
    )

    return HealthResponse(
        status="ok",
        engine=str(engine_name),
        model_size=str(model_size),
        device=str(actual_device),
        compute_type=str(actual_compute_type),
    )


@app.post(
    "/api/v1/transcribe",
    tags=["Transcription"],
    response_model=TranscriptionResult,
    summary="Транскрибация загруженного аудиофайла",
    responses={
        413: {"description": "Превышен лимит размера или длительности аудио", "model": ErrorResponse},
        503: {"description": "Достигнут лимит одновременных запросов", "model": ErrorResponse},
        200: {
            "description": "Аудиозапись успешно транскрибирована",
            "model": TranscriptionResult,
        },
        400: {
            "description": "Неподдерживаемый формат аудиофайла или передан пустой файл",
            "model": ErrorResponse,
        },
        500: {
            "description": "Внутренняя ошибка сервиса при распознавании",
            "model": ErrorResponse,
        },
    },
)
def transcribe_file(
    file: UploadFile = File(
        ...,
        description="Аудиофайл звонка (.mp3, .wav, .ogg, .m4a, .flac, .webm)",
    ),
    language: Optional[str] = Form(
        "ru",
        description="Код языка ISO 639-1 (например, 'ru') или None для автоопределения",
    ),
    beam_size: int = Form(
        5,
        ge=1,
        le=10,
        description="Размер лучевого поиска (beam search)",
    ),
    vad_filter: bool = Form(
        True,
        description="Использовать ли VAD-фильтр пауз перед транскрибацией",
    ),
    condition_on_previous_text: bool = Form(
        False,
        description="Защита от зацикливания и повторов на длинных паузах",
    ),
    initial_prompt: Optional[str] = Form(
        None,
        description="Начальный контекстный промпт/глоссарий для повышения точности терминов",
    ),
    service: BaseTranscriber = Depends(get_stt_service),
) -> TranscriptionResult:
    """
    Принимает аудиофайл через multipart/form-data, сохраняет его во временный файл,
    выполняет транскрибацию и удаляет временный файл в блоке finally.
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

        if initial_prompt in ("string", ""):
            initial_prompt = None

        PyAVInputValidator().validate(tmp_path)
        return service.transcribe(
            tmp_path,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=initial_prompt,
        )
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


@app.post(
    "/api/v1/transcribe/by-path",
    dependencies=[Depends(require_shared_access)],
    tags=["Transcription"],
    response_model=TranscriptionResult,
    summary="Транскрибация аудиофайла по локальному пути (Shared Volume)",
    responses={
        413: {"description": "Превышен лимит размера или длительности аудио", "model": ErrorResponse},
        503: {"description": "Достигнут лимит одновременных запросов", "model": ErrorResponse},
        401: {"description": "Требуется токен доступа", "model": ErrorResponse},
        403: {"description": "Доступ по пути запрещён", "model": ErrorResponse},
        200: {
            "description": "Аудиозапись успешно транскрибирована",
            "model": TranscriptionResult,
        },
        404: {
            "description": "Указанный аудиофайл не найден",
            "model": ErrorResponse,
        },
        500: {
            "description": "Внутренняя ошибка сервиса при распознавании",
            "model": ErrorResponse,
        },
    },
)
def transcribe_by_path(
    request: TranscribeByPathRequest,
    service: BaseTranscriber = Depends(get_stt_service),
) -> TranscriptionResult:
    """
    Транскрибирует аудиофайл, находящийся на локальном диске или в примонтированном общем томе.
    """
    try:
        initial_prompt = request.initial_prompt
        if initial_prompt in ("string", ""):
            initial_prompt = None

        file_path = shared_path(request.file_path, ALLOWED_AUDIO_EXTENSIONS)
        PyAVInputValidator().validate(file_path)
        return service.transcribe(
            file_path,
            language=request.language,
            beam_size=request.beam_size,
            vad_filter=request.vad_filter,
            condition_on_previous_text=request.condition_on_previous_text,
            initial_prompt=initial_prompt,
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )


def export_openapi_yaml(output_path: Union[str, Path] = "stt/openapi.yaml") -> None:
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
