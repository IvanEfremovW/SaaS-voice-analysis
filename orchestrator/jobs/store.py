"""Очередь публикации и результаты обработки в локальной SQLite."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from audio_preprocessing.api import PreprocessResponse
from stt import TranscriptionResult

from .models import JobOptions, Mode

JobStatus = Literal["queued", "running", "succeeded", "failed"]
MAX_ATTEMPTS = 3


class Job(BaseModel):
    job_id: UUID
    status: JobStatus
    result: TranscriptionResult | None = None
    error: str | None = None
    mode: Mode | None = None
    preprocessing: PreprocessResponse | None = None
    shared_input: bool = Field(default=False, exclude=True)


@dataclass(frozen=True)
class ClaimedJob:
    filename: str
    options: JobOptions | None


class JobStore(Protocol):
    def create(self, job_id: UUID, filename: str, options: JobOptions | None = None) -> None: ...
    def get(self, job_id: UUID) -> Job | None: ...
    def pending(self) -> list[UUID]: ...
    def mark_published(self, job_id: UUID) -> None: ...
    def claim(self, job_id: UUID) -> ClaimedJob | None: ...
    def finish(
        self, job_id: UUID, *, result: TranscriptionResult | None = None,
        preprocessing: PreprocessResponse | None = None, error: str | None = None,
    ) -> None: ...


class SQLiteJobStore(JobStore):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    pending INTEGER NOT NULL DEFAULT 1,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result TEXT,
                    error TEXT,
                    options TEXT,
                    preprocessing TEXT
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "options" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN options TEXT")
            if "preprocessing" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN preprocessing TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(pending) WHERE pending = 1")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def create(self, job_id: UUID, filename: str, options: JobOptions | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO jobs (job_id, filename, options) VALUES (?, ?, ?)",
                (str(job_id), filename, options.model_dump_json() if options is not None else None),
            )

    def get(self, job_id: UUID) -> Job | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id, status, result, error, options, preprocessing FROM jobs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        if row["result"] is not None:
            data["result"] = TranscriptionResult.model_validate_json(row["result"])
        if row["preprocessing"] is not None:
            data["preprocessing"] = PreprocessResponse.model_validate_json(row["preprocessing"])
        if row["options"] is not None:
            options = JobOptions.model_validate_json(row["options"])
            data.update(mode=options.mode, shared_input=options.shared_input)
        return Job.model_validate(data)

    def pending(self) -> list[UUID]:
        with self._connect() as db:
            rows = db.execute("SELECT job_id FROM jobs WHERE pending = 1 ORDER BY rowid LIMIT 100")
            return [UUID(row["job_id"]) for row in rows]

    def mark_published(self, job_id: UUID) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET pending = 0 WHERE job_id = ?", (str(job_id),))

    def claim(self, job_id: UUID) -> ClaimedJob | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = (str(job_id),)
            row = db.execute(
                "SELECT filename, status, attempts, options FROM jobs WHERE job_id = ?", key
            ).fetchone()
            if row is None or row["status"] in ("succeeded", "failed"):
                return None
            if row["attempts"] >= MAX_ATTEMPTS:
                db.execute(
                    "UPDATE jobs SET status = 'failed', error = ?, pending = 0 WHERE job_id = ?",
                    ("Исчерпаны попытки обработки", *key),
                )
                return None
            db.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1 WHERE job_id = ?", key
            )
            options = JobOptions.model_validate_json(row["options"]) if row["options"] is not None else None
            return ClaimedJob(filename=row["filename"], options=options)

    def finish(
        self, job_id: UUID, *, result: TranscriptionResult | None = None,
        preprocessing: PreprocessResponse | None = None, error: str | None = None,
    ) -> None:
        if (result is None and preprocessing is None) == (error is None):
            raise ValueError("Укажите результат или ошибку")
        with self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = ?, result = ?, preprocessing = ?, error = ?, pending = 0 "
                "WHERE job_id = ? AND status = 'running'",
                (
                    "failed" if error is not None else "succeeded",
                    result.model_dump_json() if result is not None else None,
                    preprocessing.model_dump_json() if preprocessing is not None else None,
                    error,
                    str(job_id),
                ),
            )
