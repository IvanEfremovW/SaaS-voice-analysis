"""
Интеграционные тесты для HTTP REST API сервиса предобработки аудио и VAD (FastAPI).
Проверяют валидацию входных данных, загрузку файлов, обработку ошибок,
сохранение аудио по пути, пересчет таймкодов и спецификацию OpenAPI.
"""

import base64
import io
from pathlib import Path
from typing import Generator
from fastapi.testclient import TestClient
import pytest
import soundfile as sf

from audio_preprocessing.api import (
    app,
    get_pipeline_service,
    reset_pipeline_service,
)
from audio_preprocessing.pipeline import (
    AudioPipelineConfig,
    AudioPreprocessVADPipeline,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_AUDIO_FILE = REPO_ROOT / "audio_preprocessing" / "input_test_call.mp3"


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """
    Фикстура TestClient для отправки запросов к приложению FastAPI.
    """
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client: TestClient) -> None:
    """
    1. GET /api/v1/health -> 200 OK,
    проверка полей status == 'ok', converter == 'torchaudio',
    denoiser == 'stat_spectral', vad == 'silero', target_sr == 16000.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["converter"] == "torchaudio"
    assert data["denoiser"] == "stat_spectral"
    assert data["vad"] == "silero"
    assert data["target_sr"] == 16000


def test_preprocess_upload_file_success(client: TestClient) -> None:
    """
    2. POST /api/v1/preprocess с input_test_call.mp3 и include_audio_base64=True -> 200 OK,
    проверка speech_segments, retention_pct > 0, валидное декодирование audio_wav_base64.
    """
    assert REAL_AUDIO_FILE.is_file(), f"Тестовый аудиофайл не найден: {REAL_AUDIO_FILE}"

    with open(REAL_AUDIO_FILE, "rb") as f:
        response = client.post(
            "/api/v1/preprocess",
            files={"file": ("input_test_call.mp3", f, "audio/mpeg")},
            data={"include_audio_base64": "true"},
        )

    assert response.status_code == 200
    data = response.json()

    assert data["sample_rate"] == 16000
    assert data["original_duration"] > 0
    assert data["speech_duration"] > 0
    assert data["retention_pct"] > 0
    assert data["segments_count"] == len(data["speech_segments"])
    assert len(data["speech_segments"]) > 0

    for seg in data["speech_segments"]:
        assert "start" in seg
        assert "end" in seg
        assert seg["start"] <= seg["end"]

    # Проверка декодирования Base64 в валидный 16kHz WAV
    assert data["audio_wav_base64"] is not None
    raw_wav = base64.b64decode(data["audio_wav_base64"])
    wav_buffer = io.BytesIO(raw_wav)
    audio_data, sr = sf.read(wav_buffer)
    assert sr == 16000
    assert len(audio_data) > 0


def test_preprocess_upload_unsupported_format(client: TestClient) -> None:
    """
    3. POST /api/v1/preprocess с неподдерживаемым расширением (.txt) -> 400 Bad Request.
    """
    response = client.post(
        "/api/v1/preprocess",
        files={"file": ("test.txt", b"plain text data", "text/plain")},
    )

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Неподдерживаемый формат аудиофайла" in data["detail"]


def test_preprocess_upload_empty_file(client: TestClient) -> None:
    """
    4. POST /api/v1/preprocess с пустым файлом (.wav, 0 байт) -> 400 Bad Request.
    """
    response = client.post(
        "/api/v1/preprocess",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Передан пустой аудиофайл" in data["detail"]


def test_preprocess_by_path_with_output_wav(client: TestClient, tmp_path: Path) -> None:
    """
    5. POST /api/v1/preprocess/by-path с сохранением в output_wav_path -> 200 OK,
    проверка создания выходного WAV и чтения через soundfile.
    """
    assert REAL_AUDIO_FILE.is_file(), f"Тестовый аудиофайл не найден: {REAL_AUDIO_FILE}"

    out_wav = tmp_path / "speech_only.wav"
    payload = {
        "file_path": str(REAL_AUDIO_FILE),
        "output_wav_path": str(out_wav),
        "include_audio_base64": False,
    }

    response = client.post("/api/v1/preprocess/by-path", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["output_wav_path"] == str(out_wav.resolve())
    assert out_wav.is_file()

    audio_data, sr = sf.read(str(out_wav))
    assert sr == 16000
    assert len(audio_data) > 0
    assert data["audio_wav_base64"] is None


def test_preprocess_by_path_not_found(client: TestClient) -> None:
    """
    6. POST /api/v1/preprocess/by-path с несуществующим путем -> 404 Not Found.
    """
    payload = {
        "file_path": "/non_existent/path/to/missing_file.mp3",
    }

    response = client.post("/api/v1/preprocess/by-path", json=payload)
    assert response.status_code == 404

    data = response.json()
    assert "detail" in data
    assert "не найден" in data["detail"].lower()


def test_remap_timestamps_endpoint(client: TestClient) -> None:
    """
    7. POST /api/v1/remap-timestamps -> 200 OK,
    проверка корректного пересчета сегментов транскрибации на шкалу исходного файла.
    """
    payload = {
        "transcription": {
            "text": "Я звоню вам по поводу препарата от грибка Милозол.",
            "language": "ru",
            "language_probability": 1.0,
            "duration": 4.636,
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 4.636,
                    "text": "Я звоню вам по поводу препарата от грибка Милозол.",
                    "avg_logprob": -0.312,
                    "no_speech_prob": 0.045,
                }
            ],
        },
        "speech_segments": [
            {"start": 1.762, "end": 6.398}
        ],
        "original_duration": 35.07,
    }

    response = client.post("/api/v1/remap-timestamps", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["text"] == "Я звоню вам по поводу препарата от грибка Милозол."
    assert data["duration"] == 35.07
    assert len(data["segments"]) == 1

    seg = data["segments"][0]
    assert seg["id"] == 0
    assert seg["start"] == 1.762
    assert seg["end"] == 6.398


def test_openapi_schema_available(client: TestClient) -> None:
    """
    8. GET /openapi.json -> 200 OK,
    проверка наличия всех 4 эндпоинтов:
      - /api/v1/health
      - /api/v1/preprocess
      - /api/v1/preprocess/by-path
      - /api/v1/remap-timestamps
    """
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    paths = schema.get("paths", {})

    assert "/api/v1/health" in paths
    assert "/api/v1/preprocess" in paths
    assert "/api/v1/preprocess/by-path" in paths
    assert "/api/v1/remap-timestamps" in paths


def test_dependency_override(client: TestClient) -> None:
    """
    Проверка возможности переопределения get_pipeline_service через dependency_overrides.
    """
    mock_config = AudioPipelineConfig(
        converter="torchaudio",
        denoiser=None,
        vad=None,
        target_sr=16000,
    )
    custom_pipeline = AudioPreprocessVADPipeline(config=mock_config)

    app.dependency_overrides[get_pipeline_service] = lambda: custom_pipeline
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["denoiser"] == "none"
        assert data["vad"] == "none"
    finally:
        app.dependency_overrides.clear()
