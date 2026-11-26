"""Контракты запроса и сохраняемые параметры задания."""

import os
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from stt.config import DEFAULT_MODEL_SIZE
from stt.variants import DemoVariant, variant_options

Mode = Literal["vad", "stt", "pipeline"]
Device = Literal["cpu", "gpu"]
ExecutionDevice = Literal["cpu", "gpu", "auto"]
Detector = Literal["silero", "webrtc", "energy"]


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode = "pipeline"
    variant_id: str | None = None
    device: Device | None = None
    vad: Detector | None = None
    language: str | None = None
    beam_size: int | None = Field(default=None, ge=1, le=10)
    condition_on_previous_text: bool | None = None
    initial_prompt: str | None = None
    include_audio_base64: bool = False


class ByPathRequest(JobRequest):
    file_path: str
    output_wav_path: str | None = None


class JobVariant(DemoVariant):
    supported_devices: list[Device]


class JobOptions(BaseModel):
    """Снимок профиля и настроек, необходимый для повторной доставки."""

    mode: Mode = "pipeline"
    variant_id: str | None = None
    engine: str = "faster-whisper"
    model_size: str = DEFAULT_MODEL_SIZE
    device: ExecutionDevice = "cpu"
    compute_type: str = "int8"
    vad: Detector = "silero"
    stt_options: dict[str, object] = Field(default_factory=dict)
    include_audio_base64: bool = False
    output_wav_path: str | None = None
    shared_input: bool = False


def legacy_options() -> JobOptions:
    device_names: dict[str, ExecutionDevice] = {"cuda": "gpu", "auto": "auto", "cpu": "cpu"}
    device = device_names.get(os.getenv("STT_DEVICE", "cpu"), "cpu")
    return JobOptions(
        engine=os.getenv("STT_ENGINE", "faster-whisper"),
        model_size=os.getenv("STT_MODEL_SIZE", DEFAULT_MODEL_SIZE),
        device=device,
        compute_type=os.getenv("STT_COMPUTE_TYPE", "int8"),
    )


def resolve_options(request: JobRequest, variants: dict[str, DemoVariant]) -> JobOptions:
    variant = variants.get(request.variant_id) if request.variant_id is not None else None
    if request.variant_id is not None and variant is None:
        raise HTTPException(422, "Неизвестный variant_id")

    overrides = request.model_dump(include={
        "language", "beam_size", "condition_on_previous_text", "initial_prompt"
    }, exclude_unset=True)
    if overrides.get("beam_size", 1) is None or overrides.get("condition_on_previous_text", False) is None:
        raise HTTPException(422, "beam_size и condition_on_previous_text должны иметь значение")
    output = request.output_wav_path if isinstance(request, ByPathRequest) else None

    if request.mode == "vad" and (variant or request.device or overrides):
        raise HTTPException(422, "Режим vad принимает настройки предобработки")
    if request.mode == "stt" and (request.vad or request.include_audio_base64 or output is not None):
        raise HTTPException(422, "Режим stt применяет VAD из выбранного профиля")
    if variant is None and request.mode == "stt":
        variant = variants.get("current_recovery")
        if variant is None:
            raise HTTPException(422, "Укажите variant_id из каталога профилей")

    options = legacy_options()
    options.mode = request.mode
    options.device = request.device or "cpu"
    options.vad = request.vad or "silero"
    options.include_audio_base64 = request.include_audio_base64
    options.output_wav_path = output
    options.shared_input = isinstance(request, ByPathRequest)
    if request.device == "gpu":
        options.compute_type = os.getenv("STT_GPU_COMPUTE_TYPE", "float16")
    if variant is not None:
        options.variant_id = variant.id
        options.engine = "t-one" if variant.engine == "tone" else "faster-whisper"
        options.stt_options = variant_options(variant)
    if options.engine in ("t-one", "tone"):
        if options.device == "gpu":
            raise HTTPException(422, "T-one поддерживает только CPU")
        if overrides:
            raise HTTPException(422, "Эти параметры распознавания доступны для Whisper")
    options.stt_options.update(overrides)
    if request.mode == "pipeline":
        options.stt_options["vad_filter"] = False
    return options
