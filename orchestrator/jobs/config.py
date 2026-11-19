"""Настройки локального API и воркера."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobSettings:
    audio_dir: Path
    db_path: Path
    broker_url: str

    @classmethod
    def from_env(cls) -> "JobSettings":
        return cls(
            audio_dir=Path(os.getenv("TRANSCRIPTION_AUDIO_DIR", "output/jobs/audio")).resolve(),
            db_path=Path(os.getenv("TRANSCRIPTION_DB_PATH", "output/jobs/jobs.sqlite3")).resolve(),
            broker_url=os.getenv("CELERY_BROKER_URL", "amqp://transcription:transcription-local@127.0.0.1:5672//"),
        )
