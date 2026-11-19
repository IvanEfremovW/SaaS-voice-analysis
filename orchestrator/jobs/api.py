"""HTTP API фоновой обработки звонков."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_urlsafe
from tempfile import NamedTemporaryFile
from typing import BinaryIO, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from audio_http import (
    MAX_UPLOAD_BYTES, AudioInputValidator, AudioUploadLimit, PyAVInputValidator,
    require_shared_access, shared_path,
)
from stt.api import ALLOWED_AUDIO_EXTENSIONS
from stt.variants import load_variants

from .broker import CeleryJobQueue, JobQueue, create_celery, publish_pending
from .config import JobSettings
from .models import ByPathRequest, Detector, Device, JobOptions, JobRequest, JobVariant, Mode, resolve_options
from .store import Job, JobQuotaExceeded, JobStore, token_digest

logger = logging.getLogger(__name__)
job_bearer = HTTPBearer(auto_error=False, scheme_name="JobBearer")


class JobAccepted(BaseModel):
    job_id: UUID
    status: Literal["queued"] = "queued"
    status_url: str
    access_token: str


def create_app(
    settings: JobSettings | None = None,
    *,
    store: JobStore | None = None,
    queue: JobQueue | None = None,
    validator: AudioInputValidator | None = None,
) -> FastAPI:
    settings = settings or JobSettings.from_env()
    audio_dir = settings.audio_dir
    validator = validator or PyAVInputValidator()
    variants = {variant.id: variant for variant in load_variants()}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        job_store = store or settings.open_store()
        audio_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        audio_dir.chmod(0o700)
        job_queue = queue or CeleryJobQueue(create_celery(settings.broker_url))
        app.state.job_store = job_store
        stop = asyncio.Event()

        async def publisher() -> None:
            while not stop.is_set():
                try:
                    await asyncio.to_thread(job_store.maintain)
                    await asyncio.to_thread(publish_pending, job_store, job_queue)
                except Exception:
                    logger.exception("Не удалось опубликовать задания")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(publisher())
        try:
            yield
        finally:
            stop.set()
            await task

    app = FastAPI(title="Очередь обработки звонков", lifespan=lifespan)
    app.add_middleware(AudioUploadLimit)

    def enqueue(
        source: BinaryIO, suffix: str, options: JobOptions, job_store: JobStore
    ) -> JobAccepted:
        job_id = uuid4()
        access_token = token_urlsafe(32)
        target = audio_dir / f"{job_id}{suffix}"
        with NamedTemporaryFile(dir=audio_dir, suffix=suffix, delete=False) as upload:
            staged = Path(upload.name)
        try:
            with staged.open("wb") as output:
                remaining = MAX_UPLOAD_BYTES
                while chunk := source.read(1024 * 1024):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise HTTPException(413, "Превышен лимит размера аудиофайла")
                    output.write(chunk)
            if staged.stat().st_size == 0:
                raise HTTPException(400, "Передан пустой аудиофайл")
            validator.validate(staged)
            staged.replace(target)
            try:
                job_store.create(
                    job_id, target.name, options,
                    access_digest=token_digest(access_token), input_bytes=target.stat().st_size,
                )
            except JobQuotaExceeded:
                target.unlink(missing_ok=True)
                raise HTTPException(507, "Хранилище заданий заполнено") from None
            except Exception:
                target.unlink(missing_ok=True)
                raise
        finally:
            staged.unlink(missing_ok=True)
        return JobAccepted(
            job_id=job_id, status_url=str(app.url_path_for("get_job", job_id=job_id)), access_token=access_token,
        )

    @app.post(
        "/api/v1/jobs", response_model=JobAccepted, status_code=202,
        responses={507: {"description": "Хранилище заданий заполнено"}},
    )
    def submit_job(
        file: UploadFile, request: Request, response: Response, mode: Mode = Form("pipeline"),
        variant_id: str | None = Form(None), device: Device | None = Form(None),
        vad: Detector | None = Form(None),
        language: str | None = Form(None), beam_size: int | None = Form(None, ge=1, le=10),
        condition_on_previous_text: bool | None = Form(None), initial_prompt: str | None = Form(None),
        include_audio_base64: bool = Form(False),
    ) -> JobAccepted:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(415, "Неподдерживаемый формат аудиофайла")
        optional = {
            "variant_id": variant_id, "device": device, "vad": vad, "language": language,
            "beam_size": beam_size, "condition_on_previous_text": condition_on_previous_text,
            "initial_prompt": initial_prompt,
        }
        options = resolve_options(JobRequest.model_validate({
            "mode": mode, "include_audio_base64": include_audio_base64,
            **{key: value for key, value in optional.items() if value is not None},
        }), variants)
        response.headers["Cache-Control"] = "no-store"
        return enqueue(file.file, suffix, options, request.app.state.job_store)

    @app.post(
        "/api/v1/jobs/by-path", response_model=JobAccepted, status_code=202,
        dependencies=[Depends(require_shared_access)],
        responses={507: {"description": "Хранилище заданий заполнено"}},
    )
    def submit_by_path(body: ByPathRequest, request: Request, response: Response) -> JobAccepted:
        options = resolve_options(body, variants)
        path = shared_path(body.file_path, ALLOWED_AUDIO_EXTENSIONS)
        if options.output_wav_path is not None:
            output = shared_path(options.output_wav_path, {".wav"}, output=True)
            if not output.parent.is_dir():
                raise HTTPException(400, "Выходной каталог должен существовать")
            if output.exists():
                raise HTTPException(409, "Выходной файл уже существует")
            options.output_wav_path = str(output)
        try:
            with path.open("rb") as source:
                response.headers["Cache-Control"] = "no-store"
                return enqueue(source, path.suffix.lower(), options, request.app.state.job_store)
        except FileNotFoundError:
            raise HTTPException(404, "Исходный аудиофайл не найден") from None

    @app.get("/api/v1/jobs/variants", response_model=list[JobVariant])
    def list_variants() -> list[JobVariant]:
        return [
            JobVariant(
                **variant.model_dump(),
                supported_devices=["cpu"] if variant.engine == "tone" else ["cpu", "gpu"],
            )
            for variant in variants.values()
        ]

    @app.get(
        "/api/v1/jobs/{job_id}", response_model=Job, response_model_exclude_none=True,
        responses={401: {"description": "Требуется токен задания"}, 404: {"description": "Задание не найдено"}},
    )
    def get_job(
        job_id: UUID, request: Request, response: Response,
        authorization: HTTPAuthorizationCredentials | None = Depends(job_bearer),
    ) -> Job:
        job_store: JobStore = request.app.state.job_store
        access = job_store.access(job_id)
        if access is None:
            raise HTTPException(404, "Задание не найдено")
        if access.digest is None and access.legacy_shared:
            require_shared_access(f"Bearer {authorization.credentials}" if authorization else None)
        elif authorization is None or not access.accepts(authorization.credentials):
            raise HTTPException(401, "Требуется токен задания", headers={"WWW-Authenticate": "Bearer"})
        job = job_store.get(job_id)
        if job is None:
            raise HTTPException(404, "Задание не найдено")
        response.headers["Cache-Control"] = "no-store"
        return job

    return app


app = create_app()
