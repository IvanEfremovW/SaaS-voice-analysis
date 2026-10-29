"""
Интеграционные тесты для HTTP REST API сервиса транскрибации речи (FastAPI).
Проверяют валидацию входных данных, загрузку файлов, обработку ошибок,
корректность эндпоинтов транскрибации и спецификации OpenAPI.
"""

from pathlib import Path
from typing import Generator
from fastapi.testclient import TestClient
import pytest

from stt import TranscriberConfig, get_transcriber
from stt.api import app, get_stt_service

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_AUDIO_FILE = REPO_ROOT / "audio_preprocessing" / "input_test_call.mp3"


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """
    Фикстура TestClient с переопределенной зависимостью get_stt_service на модель 'tiny'
    для быстрых и детерминированных тестов инференса.
    """
    tiny_config = TranscriberConfig(model_size="tiny", device="cuda")
    tiny_service = get_transcriber(config=tiny_config)

    app.dependency_overrides[get_stt_service] = lambda: tiny_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_endpoint(client: TestClient) -> None:
    """
    1. GET /api/v1/health -> 200 OK,
    проверка полей status == 'ok', engine, device, compute_type, model_size.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert "faster-whisper" in data["engine"]
    assert data["model_size"] == "tiny"
    assert data["device"] in ("cuda", "cpu")
    assert len(data["compute_type"]) > 0


def test_transcribe_upload_file_success(client: TestClient) -> None:
    """
    2. POST /api/v1/transcribe с реальным файлом input_test_call.mp3 -> 200 OK,
    валидный TranscriptionResult, language == 'ru', непустые segments.
    """
    assert REAL_AUDIO_FILE.is_file(), f"Тестовый аудиофайл не найден: {REAL_AUDIO_FILE}"

    with open(REAL_AUDIO_FILE, "rb") as f:
        response = client.post(
            "/api/v1/transcribe",
            files={"file": ("input_test_call.mp3", f, "audio/mpeg")},
            data={
                "language": "ru",
                "beam_size": 5,
                "vad_filter": True,
                "condition_on_previous_text": False,
            },
        )

    assert response.status_code == 200
    data = response.json()

    assert data["language"] == "ru"
    assert data["language_probability"] > 0.5
    assert data["duration"] > 0
    assert len(data["text"].strip()) > 0
    assert len(data["segments"]) > 0

    first_segment = data["segments"][0]
    assert "id" in first_segment
    assert "start" in first_segment
    assert "end" in first_segment
    assert "text" in first_segment
    assert first_segment["start"] <= first_segment["end"]
    assert len(first_segment["text"]) > 0


def test_transcribe_upload_unsupported_extension(client: TestClient) -> None:
    """
    3. POST /api/v1/transcribe с неподдерживаемым расширением (test.txt) -> 400 Bad Request.
    """
    response = client.post(
        "/api/v1/transcribe",
        files={"file": ("test.txt", b"plain text data", "text/plain")},
    )

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Неподдерживаемый формат аудиофайла" in data["detail"]


def test_transcribe_upload_empty_file(client: TestClient) -> None:
    """
    4. POST /api/v1/transcribe с пустым файлом (empty.wav, 0 байт) -> 400 Bad Request.
    """
    response = client.post(
        "/api/v1/transcribe",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "Передан пустой аудиофайл" in data["detail"]


def test_transcribe_by_path_success(client: TestClient) -> None:
    """
    5. POST /api/v1/transcribe/by-path с путем к реальному файлу -> 200 OK,
    валидный TranscriptionResult.
    """
    assert REAL_AUDIO_FILE.is_file(), f"Тестовый аудиофайл не найден: {REAL_AUDIO_FILE}"

    payload = {
        "file_path": str(REAL_AUDIO_FILE),
        "language": "ru",
        "beam_size": 5,
        "vad_filter": False,
        "condition_on_previous_text": False,
    }

    response = client.post("/api/v1/transcribe/by-path", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["language"] == "ru"
    assert len(data["text"].strip()) > 0
    assert len(data["segments"]) > 0
    assert data["duration"] > 0


def test_transcribe_by_path_not_found(client: TestClient) -> None:
    """
    6. POST /api/v1/transcribe/by-path с несуществующим путем -> 404 Not Found.
    """
    payload = {
        "file_path": "/non_existent/path/to/missing_call.mp3",
        "language": "ru",
    }

    response = client.post("/api/v1/transcribe/by-path", json=payload)
    assert response.status_code == 404

    data = response.json()
    assert "detail" in data
    assert "не найден" in data["detail"].lower()


def test_openapi_schema_available(client: TestClient) -> None:
    """
    7. GET /openapi.json -> 200 OK,
    проверка наличия зарегистрированных эндпоинтов:
      - /api/v1/health
      - /api/v1/transcribe
      - /api/v1/transcribe/by-path
    """
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    paths = schema.get("paths", {})

    assert "/api/v1/health" in paths
    assert "/api/v1/transcribe" in paths
    assert "/api/v1/transcribe/by-path" in paths
