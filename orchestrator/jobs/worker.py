"""Celery-воркер сквозной обработки звонков."""

import logging
import sqlite3
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from celery.exceptions import Reject
from fastapi import HTTPException

from audio_http import AudioInputValidator, PyAVInputValidator
from .broker import TASK_NAME, create_celery
from .config import JobSettings
from .execution import JobFailure, JobOutput, execute_job
from .models import JobOptions
from .store import JobStore, SQLiteJobStore

logger = logging.getLogger(__name__)
settings = JobSettings.from_env()
app = create_celery(settings.broker_url)


@lru_cache(maxsize=1)
def get_store() -> JobStore:
    return SQLiteJobStore(settings.db_path)


def process_job(
    job_id: UUID,
    audio_dir: Path,
    store: JobStore,
    validator: AudioInputValidator,
    execute: Callable[[UUID, Path, JobOptions | None], JobOutput] = execute_job,
) -> None:
    # Режим solo сериализует доставки в единственном воркере.
    # Повторная доставка после падения продолжает с сохранённого счётчика.
    while (job := store.claim(job_id)) is not None:
        path = audio_dir / job.filename
        if not path.is_file():
            store.finish(job_id, error="Исходный аудиофайл не найден")
            return
        try:
            validator.validate(path)
        except HTTPException as error:
            store.finish(job_id, error=str(error.detail))
            return

        try:
            output = execute(job_id, path, job.options)
        except (JobFailure, HTTPException) as error:
            store.finish(job_id, error=str(error.detail if isinstance(error, HTTPException) else error))
            return
        except Exception:
            logger.exception("Ошибка обработки задания %s", job_id)
            continue
        store.finish(job_id, result=output.result, preprocessing=output.preprocessing)
        if output.staged_wav is not None:
            try:
                output.staged_wav.unlink(missing_ok=True)
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
            PyAVInputValidator(),
        )
    except (sqlite3.Error, OSError) as error:
        logger.exception("Хранилище задания %s недоступно", job_id)
        raise Reject("Хранилище недоступно", requeue=True) from error
