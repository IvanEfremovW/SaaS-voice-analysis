"""Настраиваемые стратегии распознавания поверх общего STT-интерфейса."""

import os
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from stt.interfaces import BaseTranscriber, TranscriptionResult


class DemoVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    label: str
    description: str
    engine: Literal["whisper", "tone"]
    options: dict[str, object]


def load_variants() -> list[DemoVariant]:
    path = Path(os.getenv("DEMO_VARIANTS_CONFIG", str(Path(__file__).with_name("variants.json"))))
    variants = TypeAdapter(list[DemoVariant]).validate_json(path.read_text(encoding="utf-8"))
    if not variants or len({variant.id for variant in variants}) != len(variants):
        raise ValueError("Список вариантов должен быть непустым, с уникальными id")
    return variants


class ConfiguredTranscriber(BaseTranscriber):
    """Применяет параметры варианта, не меняя общую загруженную модель."""

    def __init__(self, service: BaseTranscriber, variant: DemoVariant) -> None:
        self._service = service
        self._variant = variant

    @property
    def name(self) -> str:
        return f"{self._service.name}/{self._variant.id}"

    def transcribe(self, audio: str | Path | np.ndarray, **kwargs: object) -> TranscriptionResult:
        return self._service.transcribe(audio, **{
            **kwargs,
            "language": "ru",
            "beam_size": 5,
            "condition_on_previous_text": False,
            "initial_prompt": None,
            "word_timestamps": True,
            **self._variant.options,
        })
