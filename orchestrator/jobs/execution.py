"""Локальное выполнение выбранного режима обработки."""

import base64
import io
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from uuid import UUID

import soundfile as sf
from fastapi import HTTPException

from audio_decode import AudioDecodeError
from audio_http import shared_path
from audio_preprocessing import (
    AudioPipelineConfig, AudioPipelineResult, AudioPreprocessVADPipeline, get_audio_pipeline,
)
from audio_preprocessing.api import PreprocessResponse, SpeechSegmentDTO
from orchestrator.loaders import LocalMockAudioLoader
from orchestrator.pipeline import remap_transcription_result
from stt import BaseTranscriber, TranscriberConfig, TranscriptionResult, get_transcriber
from stt.transcriber import TranscriberDeviceError

from .models import Detector, JobOptions, legacy_options


@dataclass(frozen=True)
class JobOutput:
    result: TranscriptionResult | None = None
    preprocessing: PreprocessResponse | None = None
    wav_to_publish: bytes | None = None


class JobFailure(RuntimeError):
    """Ошибка, которую повторный запуск с теми же параметрами не устранит."""


@lru_cache(maxsize=3)
def get_preprocessor(vad: Detector) -> AudioPreprocessVADPipeline:
    return get_audio_pipeline(AudioPipelineConfig(vad=vad))


@lru_cache(maxsize=3)
def get_job_transcriber(
    engine: str,
    model_size: str,
    device: Literal["cpu", "cuda", "auto"],
    compute_type: str,
    require_gpu: bool,
) -> BaseTranscriber:
    config = TranscriberConfig(
        model_size=model_size, device=device, compute_type=compute_type,
        allow_cuda_fallback=not require_gpu,
    )
    try:
        service = get_transcriber(engine, config)
    except TranscriberDeviceError as error:
        raise JobFailure(str(error)) from error
    except ImportError as error:
        if engine in ("tone", "t-one"):
            raise JobFailure("Не установлены зависимости T-one") from error
        raise
    except RuntimeError as error:
        if require_gpu:
            raise JobFailure("Не удалось инициализировать Whisper на CUDA") from error
        raise
    if require_gpu and getattr(service, "actual_device", None) != "cuda":
        raise JobFailure("Не удалось запустить Whisper на CUDA")
    return service


def encode_wav(preprocessing: AudioPipelineResult) -> bytes:
    with io.BytesIO() as wav:
        sf.write(wav, preprocessing.speech_only_audio, preprocessing.sample_rate, format="WAV", subtype="PCM_16")
        return wav.getvalue()


def publish_wav(job_id: UUID, destination: Path, wav: bytes) -> Path:
    # Сохраняем исходную ссылку до фиксации результата в SQLite. После падения
    # воркер отличает собственный опубликованный файл от файла другого задания.
    staged = destination.with_name(f".job-{job_id}.wav")
    if not staged.exists():
        with NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temp = Path(stream.name)
            try:
                stream.write(wav)
                stream.flush()
                temp.replace(staged)
            finally:
                temp.unlink(missing_ok=True)
    try:
        os.link(staged, destination)
    except FileExistsError:
        if not staged.samefile(destination):
            staged.unlink(missing_ok=True)
            raise JobFailure("Выходной файл уже существует") from None
    return staged


def execute_job(job_id: UUID, path: Path, saved_options: JobOptions | None) -> JobOutput:
    options = saved_options if saved_options is not None else legacy_options()
    try:
        audio, sr = LocalMockAudioLoader().load(path)
    except AudioDecodeError as error:
        raise JobFailure(str(error)) from error
    preparation = None
    if options.mode != "stt":
        preparation = get_preprocessor(options.vad).process_detailed(audio, sr=sr)

    transcript = None
    if options.mode != "vad":
        if preparation is not None and not preparation.speech_only_audio.size:
            transcript = TranscriptionResult(
                text="", language=str(options.stt_options.get("language", "ru") or "unknown"),
                language_probability=0, duration=preparation.original_duration,
                segments=[],
            )
        else:
            device = "cuda" if options.device == "gpu" else options.device
            service = get_job_transcriber(
                options.engine, options.model_size, device, options.compute_type,
                saved_options is not None and options.device == "gpu",
            )
            source = preparation.speech_only_audio if preparation is not None else audio
            transcript = service.transcribe(source, **options.stt_options)
            if preparation is not None:
                transcript = remap_transcription_result(
                    transcript, preparation.speech_segments, preparation.original_duration,
                )

    if preparation is None or saved_options is None:
        return JobOutput(result=transcript)

    output_path = options.output_wav_path
    audio_base64 = None
    wav = None
    if output_path is not None or options.include_audio_base64:
        wav = encode_wav(preparation)
        if options.include_audio_base64:
            audio_base64 = base64.b64encode(wav).decode("ascii")

    return JobOutput(
        result=transcript,
        preprocessing=PreprocessResponse(
            sample_rate=preparation.sample_rate,
            original_duration=preparation.original_duration,
            speech_duration=preparation.speech_duration,
            retention_pct=preparation.retention_pct,
            segments_count=len(preparation.speech_segments),
            speech_segments=[SpeechSegmentDTO(**segment) for segment in preparation.speech_segments],
            output_wav_path=output_path,
            audio_wav_base64=audio_base64,
        ),
        wav_to_publish=wav if output_path is not None else None,
    )


def publish_job_output(job_id: UUID, output: JobOutput) -> tuple[PreprocessResponse, Path]:
    prep = output.preprocessing
    if prep is None or prep.output_wav_path is None or output.wav_to_publish is None:
        raise ValueError("Нет WAV для публикации")
    destination = shared_path(prep.output_wav_path, {".wav"}, output=True)
    if not destination.parent.is_dir():
        raise HTTPException(400, "Выходной каталог должен существовать")
    staged = publish_wav(job_id, destination, output.wav_to_publish)
    return prep.model_copy(update={
        "output_wav_path": str(destination),
        "audio_wav_base64": (
            base64.b64encode(staged.read_bytes()).decode("ascii")
            if prep.audio_wav_base64 is not None else None
        ),
    }), staged
