"""Очередь публикации и результаты обработки в локальной SQLite."""

import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from secrets import compare_digest
from time import time
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from audio_preprocessing.api import PreprocessResponse
from stt import TranscriptionResult

from .models import JobOptions, Mode

JobStatus = Literal["queued", "running", "succeeded", "failed"]
MAX_ATTEMPTS = 3
LEASE_SECONDS = 60
logger = logging.getLogger(__name__)


class JobQuotaExceeded(RuntimeError):
    """Хранилище заданий достигло установленного лимита."""


class Job(BaseModel):
    job_id: UUID
    status: JobStatus
    result: TranscriptionResult | None = None
    error: str | None = None
    mode: Mode | None = None
    preprocessing: PreprocessResponse | None = None


@dataclass(frozen=True)
class ClaimedJob:
    filename: str
    options: JobOptions | None
    attempt: int


@dataclass(frozen=True)
class JobAccess:
    digest: str | None
    legacy_shared: bool

    def accepts(self, token: str) -> bool:
        return self.digest is not None and compare_digest(self.digest, token_digest(token))


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


class JobStore(Protocol):
    def create(
        self, job_id: UUID, filename: str, options: JobOptions | None = None,
        *, access_digest: str | None = None, input_bytes: int = 0,
    ) -> None: ...
    def get(self, job_id: UUID) -> Job | None: ...
    def access(self, job_id: UUID) -> JobAccess | None: ...
    def pending(self) -> list[UUID]: ...
    def mark_published(self, job_id: UUID) -> None: ...
    def claim(self, job_id: UUID) -> ClaimedJob | None: ...
    def renew(self, job_id: UUID, attempt: int) -> bool: ...
    def retry(self, job_id: UUID, attempt: int) -> bool: ...
    def finish(
        self, job_id: UUID, attempt: int, *, result: TranscriptionResult | None = None,
        preprocessing: PreprocessResponse | None = None, error: str | None = None,
        before_commit: Callable[[], PreprocessResponse] | None = None,
    ) -> bool: ...
    def maintain(self) -> None: ...


class SQLiteJobStore(JobStore):
    def __init__(
        self, path: Path, *, audio_dir: Path | None = None, max_jobs: int = 1000,
        max_bytes: int = 2 * 1024**3, retention_seconds: int = 7 * 86400,
        clock: Callable[[], float] = time,
    ) -> None:
        self.path = path
        self.audio_dir = audio_dir
        self.max_jobs = max_jobs
        self.max_bytes = max_bytes
        self.retention_seconds = retention_seconds
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Создаём файл до SQLite, чтобы права действовали и для первой транзакции.
        with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR, 0o600), "rb") as database:
            if hasattr(os, "fchmod"):
                os.fchmod(database.fileno(), 0o600)
            else:
                path.chmod(0o600)
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
                    error TEXT
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            additions = {
                "options": "TEXT", "preprocessing": "TEXT", "access_digest": "TEXT",
                "input_bytes": "INTEGER NOT NULL DEFAULT 0", "record_bytes": "INTEGER NOT NULL DEFAULT 0",
                "created_at": "REAL NOT NULL DEFAULT 0", "finished_at": "REAL",
                "lease_until": "REAL",
            }
            for name, kind in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
            if "created_at" not in columns:
                now = self.clock()
                db.execute("UPDATE jobs SET created_at = ?", (now,))
                db.execute("UPDATE jobs SET finished_at = ? WHERE status IN ('succeeded', 'failed')", (now,))
            if "record_bytes" not in columns:
                db.execute("""
                    UPDATE jobs SET record_bytes = coalesce(length(cast(result AS BLOB)), 0)
                        + coalesce(length(cast(preprocessing AS BLOB)), 0)
                        + coalesce(length(cast(options AS BLOB)), 0)
                """)
            if "input_bytes" not in columns and audio_dir is not None:
                for row in db.execute("SELECT job_id, filename FROM jobs").fetchall():
                    source = audio_dir / Path(row["filename"]).name
                    try:
                        size = source.stat().st_size
                    except FileNotFoundError:
                        size = 0
                    db.execute("UPDATE jobs SET input_bytes = ? WHERE job_id = ?", (size, row["job_id"]))
            db.execute("CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(pending) WHERE pending = 1")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA secure_delete = ON")
            yield db

    def _usage(self, db: sqlite3.Connection) -> tuple[int, int]:
        row = db.execute(
            "SELECT count(*), coalesce(sum(input_bytes + record_bytes), 0) FROM jobs"
        ).fetchone()
        return row[0], row[1]

    def create(
        self, job_id: UUID, filename: str, options: JobOptions | None = None,
        *, access_digest: str | None = None, input_bytes: int = 0,
    ) -> None:
        payload = options.model_dump_json() if options is not None else None
        options_size = self._bytes(payload)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count, used = self._usage(db)
            if count >= self.max_jobs or used + input_bytes + options_size > self.max_bytes:
                raise JobQuotaExceeded
            db.execute("""
                INSERT INTO jobs (job_id, filename, options, access_digest, input_bytes, record_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(job_id), filename, payload, access_digest, input_bytes, options_size, self.clock()))

    @staticmethod
    def _bytes(payload: str | None) -> int:
        return len(payload.encode()) if payload is not None else 0

    def access(self, job_id: UUID) -> JobAccess | None:
        with self._connect() as db:
            row = db.execute("""
                SELECT access_digest, json_extract(options, '$.shared_input') AS shared
                FROM jobs WHERE job_id = ?
            """, (str(job_id),)).fetchone()
        if row is None:
            return None
        return JobAccess(row["access_digest"], bool(row["shared"]))

    def get(self, job_id: UUID) -> Job | None:
        with self._connect() as db:
            row = db.execute("""
                SELECT job_id, status, result, error, options, preprocessing FROM jobs WHERE job_id = ?
            """, (str(job_id),)).fetchone()
        if row is None:
            return None
        data = dict(row)
        if row["result"] is not None:
            data["result"] = TranscriptionResult.model_validate_json(row["result"])
        if row["preprocessing"] is not None:
            data["preprocessing"] = PreprocessResponse.model_validate_json(row["preprocessing"])
        if row["options"] is not None:
            data["mode"] = JobOptions.model_validate_json(row["options"]).mode
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
            now = self.clock()
            key = str(job_id)
            row = db.execute(
                "SELECT filename, status, attempts, options, lease_until FROM jobs WHERE job_id = ?", (key,),
            ).fetchone()
            if row is None or row["status"] in ("succeeded", "failed"):
                return None
            if row["status"] == "running" and (row["lease_until"] or 0) > now:
                return None
            if row["attempts"] >= MAX_ATTEMPTS:
                db.execute("""
                    UPDATE jobs SET status = 'failed', error = ?, pending = 0,
                        lease_until = NULL, finished_at = ? WHERE job_id = ?
                """, ("Исчерпаны попытки обработки", now, key))
                return None
            attempt = row["attempts"] + 1
            db.execute("""
                UPDATE jobs SET status = 'running', attempts = ?, pending = 0,
                    lease_until = ? WHERE job_id = ?
            """, (attempt, now + LEASE_SECONDS, key))
            options = JobOptions.model_validate_json(row["options"]) if row["options"] is not None else None
            return ClaimedJob(filename=row["filename"], options=options, attempt=attempt)

    def renew(self, job_id: UUID, attempt: int) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = self.clock()
            updated = db.execute("""
                UPDATE jobs SET lease_until = ? WHERE job_id = ? AND attempts = ?
                    AND status = 'running' AND lease_until > ?
            """, (now + LEASE_SECONDS, str(job_id), attempt, now))
            return updated.rowcount == 1

    def retry(self, job_id: UUID, attempt: int) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("""
                UPDATE jobs SET status = 'queued', pending = 1, lease_until = NULL
                WHERE job_id = ? AND attempts = ? AND status = 'running' AND lease_until > ?
            """, (str(job_id), attempt, self.clock()))
            return updated.rowcount == 1

    def finish(
        self, job_id: UUID, attempt: int, *, result: TranscriptionResult | None = None,
        preprocessing: PreprocessResponse | None = None, error: str | None = None,
        before_commit: Callable[[], PreprocessResponse] | None = None,
    ) -> bool:
        if (result is None and preprocessing is None) == (error is None):
            raise ValueError("Укажите результат или ошибку")
        transcript = result.model_dump_json() if result is not None else None
        prep = preprocessing.model_dump_json() if preprocessing is not None else None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = str(job_id)
            now = self.clock()
            owned = db.execute("""
                SELECT 1 FROM jobs WHERE job_id = ? AND attempts = ?
                    AND status = 'running' AND lease_until > ?
            """, (key, attempt, now)).fetchone()
            if owned is None:
                return False
            _, used = self._usage(db)
            result_bytes = self._bytes(transcript) + self._bytes(prep)
            if error is None and before_commit is not None and used + result_bytes <= self.max_bytes:
                prep = before_commit().model_dump_json()
                result_bytes = self._bytes(transcript) + self._bytes(prep)
            if error is None and used + result_bytes > self.max_bytes:
                transcript = prep = None
                error = "Недостаточно места для результата задания"
                result_bytes = 0
            db.execute("""
                UPDATE jobs SET status = ?, result = ?, preprocessing = ?, error = ?,
                    pending = 0, lease_until = NULL, finished_at = ?, record_bytes = record_bytes + ?
                WHERE job_id = ?
            """, ("failed" if error is not None else "succeeded", transcript, prep, error,
                  self.clock(), result_bytes, key))
            return True

    def maintain(self) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = self.clock()
            db.execute("""
                UPDATE jobs SET status = 'queued', pending = 1, lease_until = NULL
                WHERE status = 'running' AND coalesce(lease_until, 0) <= ?
            """, (now,))
            if self.audio_dir is None:
                return
            expired = db.execute("""
                SELECT job_id, filename FROM jobs
                WHERE status != 'running' AND coalesce(finished_at, created_at) <= ? LIMIT 100
            """, (now - self.retention_seconds,)).fetchall()
            for row in expired:
                try:
                    (self.audio_dir / Path(row["filename"]).name).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Не удалось удалить запись задания %s", row["job_id"], exc_info=True)
                    continue
                db.execute("DELETE FROM jobs WHERE job_id = ?", (row["job_id"],))
