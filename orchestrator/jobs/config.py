"""Настройки локального API и воркера."""

import os
from dataclasses import dataclass
from pathlib import Path

from .store import SQLiteJobStore


@dataclass(frozen=True)
class JobSettings:
    audio_dir: Path
    db_path: Path
    broker_url: str

    max_jobs: int = 1000
    max_bytes: int = 2 * 1024**3
    retention_seconds: int = 7 * 86400

    def __post_init__(self) -> None:
        if min(self.max_jobs, self.max_bytes, self.retention_seconds) <= 0:
            raise ValueError("Квоты и срок хранения заданий должны быть положительными")

    def open_store(self) -> SQLiteJobStore:
        default_path = Path("output/jobs/jobs.sqlite3").resolve()
        if self.db_path == default_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.db_path.parent.chmod(0o700)
        return SQLiteJobStore(
            self.db_path, audio_dir=self.audio_dir, max_jobs=self.max_jobs,
            max_bytes=self.max_bytes, retention_seconds=self.retention_seconds,
        )

    @classmethod
    def from_env(cls) -> "JobSettings":
        return cls(
            audio_dir=Path(os.getenv("TRANSCRIPTION_AUDIO_DIR", "output/jobs/audio")).resolve(),
            db_path=Path(os.getenv("TRANSCRIPTION_DB_PATH", "output/jobs/jobs.sqlite3")).resolve(),
            max_jobs=int(os.getenv("TRANSCRIPTION_MAX_JOBS", "1000")),
            max_bytes=int(os.getenv("TRANSCRIPTION_MAX_BYTES", str(2 * 1024**3))),
            retention_seconds=int(os.getenv("TRANSCRIPTION_RETENTION_SECONDS", str(7 * 86400))),
            broker_url=os.getenv("CELERY_BROKER_URL", "amqp://transcription:transcription-local@127.0.0.1:5672//"),
        )
