"""Celery-воркер сквозной обработки звонков."""

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from threading import Event, Thread
from uuid import UUID

from celery.exceptions import Reject
from fastapi import HTTPException

from audio_http import AudioInputValidator
from audio_preprocessing.api import PreprocessResponse
from .broker import TASK_NAME, create_celery
from .config import JobSettings
from .execution import JobFailure, JobOutput, execute_job, publish_job_output
from .models import JobOptions
from .store import LEASE_SECONDS, JobStore

logger = logging.getLogger(__name__)
settings = JobSettings.from_env()
app = create_celery(settings.broker_url)


@lru_cache(maxsize=1)
def get_store() -> JobStore:
    return settings.open_store()


@contextmanager
def renew_claim(store: JobStore, job_id: UUID, attempt: int) -> Iterator[None]:
    stop = Event()

    def heartbeat() -> None:
        while not stop.wait(LEASE_SECONDS / 3):
            try:
                if not store.renew(job_id, attempt):
                    return
            except sqlite3.Error:
                logger.warning("Не удалось продлить попытку задания %s", job_id, exc_info=True)

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def process_job(
    job_id: UUID,
    audio_dir: Path,
    store: JobStore,
    validator: AudioInputValidator | None = None,
    execute: Callable[[UUID, Path, JobOptions | None], JobOutput] = execute_job,
) -> None:
    while (job := store.claim(job_id)) is not None:
        path = audio_dir / job.filename
        staged_wav = None

        def publish_output() -> PreprocessResponse:
            nonlocal staged_wav
            prep, staged_wav = publish_job_output(job_id, output)
            return prep

        with renew_claim(store, job_id, job.attempt):
            try:
                if not path.is_file():
                    raise JobFailure("Исходный аудиофайл не найден")
                if validator is not None:
                    validator.validate(path)
                output = execute(job_id, path, job.options)
                store.finish(
                    job_id, job.attempt, result=output.result, preprocessing=output.preprocessing,
                    before_commit=publish_output if output.wav_to_publish is not None else None,
                )
            except (JobFailure, HTTPException) as error:
                store.finish(job_id, job.attempt, error=str(error.detail if isinstance(error, HTTPException) else error))
                return
            except (sqlite3.Error, OSError):
                raise
            except Exception:
                logger.exception("Ошибка обработки задания %s", job_id)
                if not store.retry(job_id, job.attempt):
                    return
                continue
        if staged_wav is not None:
            try:
                staged_wav.unlink(missing_ok=True)
            except OSError:
                logger.warning("Не удалось удалить временный WAV задания %s", job_id, exc_info=True)
        return


@app.task(name=TASK_NAME)
def transcribe_call(job_id: str) -> None:
    try:
        process_job(
            UUID(job_id),
            settings.audio_dir,
            get_store(),
        )
    except (sqlite3.Error, OSError) as error:
        logger.exception("Хранилище задания %s недоступно", job_id)
        raise Reject("Хранилище недоступно", requeue=True) from error
