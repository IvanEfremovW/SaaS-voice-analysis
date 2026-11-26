"""Локальный интерфейс транскрибации записей звонков."""

import logging
from pathlib import Path
from threading import Lock
from time import perf_counter

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from audio_http import AudioUploadLimit
from stt import get_transcriber
from stt.api import get_stt_service, transcribe_file
from stt.interfaces import BaseTranscriber, TranscriptionResult

from .variants import ConfiguredTranscriber, DemoVariant, load_variants


logger = logging.getLogger(__name__)
_tone_lock = Lock()
_tone: BaseTranscriber | None = None
_inference_lock = Lock()
_variants = load_variants()


class DemoResult(BaseModel):
    transcript: TranscriptionResult
    elapsed_s: float


def get_tone_service() -> BaseTranscriber:
    global _tone
    with _tone_lock:
        if _tone is None:
            _tone = get_transcriber("t-one")
        return _tone


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(AudioUploadLimit)
app.add_api_route(
    "/api/transcribe",
    transcribe_file,
    methods=["POST"],
    response_model=TranscriptionResult,
)


@app.post("/api/transcribe/t-one", response_model=TranscriptionResult)
def transcribe_with_tone(file: UploadFile) -> TranscriptionResult:
    try:
        return transcribe_file(
            file=file, language="ru", beam_size=5, vad_filter=False,
            condition_on_previous_text=False, initial_prompt=None, service=get_tone_service(),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Ошибка распознавания T-one")
        raise HTTPException(503, "T-one недоступен. Проверьте зависимости и веса модели.") from error


@app.get("/api/variants", response_model=list[DemoVariant])
def list_variants() -> list[DemoVariant]:
    return _variants


@app.post("/api/transcribe/{variant_id}", response_model=DemoResult)
def transcribe_variant(variant_id: str, file: UploadFile) -> DemoResult:
    variant = next((item for item in _variants if item.id == variant_id), None)
    if variant is None:
        raise HTTPException(404, "Неизвестный вариант транскрибации")
    # Общая модель и измерения защищены от конкурирующих прогонов демо.
    with _inference_lock:
        try:
            service = get_tone_service() if variant.engine == "tone" else get_stt_service()
            started = perf_counter()
            result = transcribe_file(
                file=file, language="ru", beam_size=5, vad_filter=True,
                condition_on_previous_text=False, initial_prompt=None,
                service=ConfiguredTranscriber(service, variant),
            )
            return DemoResult(transcript=result, elapsed_s=round(perf_counter() - started, 3))
        except HTTPException:
            raise
        except Exception as error:
            logger.exception("Ошибка распознавания варианта %s", variant.id)
            raise HTTPException(503, "Вариант недоступен. Проверьте зависимости и веса модели.") from error


dist = Path(__file__).with_name("dist")
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True))
