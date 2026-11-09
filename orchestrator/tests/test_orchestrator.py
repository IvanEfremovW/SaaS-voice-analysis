"""
Интеграционные и модульные тесты для внешнего оркестратора (CallProcessingPipeline).
Проверяют:
1. Архитектурную изоляцию («Чёрные ящики»): отсутствие перекрестных импортов.
2. Работу пайплайна с включенной предобработкой (In-Memory).
3. Работу пайплайна с выключенной предобработкой (сырое аудио напрямую в STT).
4. Работу пайплайна поверх HTTP REST API микросервисов (через TestClient).
5. Точность маппинга таймкодов (remap_transcription_result).
"""

import ast
from pathlib import Path
from typing import List, Set
from fastapi.testclient import TestClient
import numpy as np
import pytest

from audio_preprocessing import get_audio_pipeline
from audio_preprocessing.api import app as prep_app
from orchestrator import (
    CallProcessingPipeline,
    LocalMockAudioLoader,
    RestPreprocessorClient,
    RestTranscriberClient,
    remap_time_to_original,
    remap_transcription_result,
)
from stt import FasterWhisperTranscriber, TranscriberConfig, get_transcriber
from stt.api import app as stt_app, get_stt_service
from stt.interfaces import TranscriptionResult, TranscriptionSegment

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_AUDIO_FILE = REPO_ROOT / "audio_preprocessing" / "input_test_call.mp3"


@pytest.fixture(scope="session")
def tiny_transcriber() -> FasterWhisperTranscriber:
    """Транскрибатор с моделью 'tiny' на CPU для детерминированных и быстрых тестов."""
    config = TranscriberConfig(model_size="tiny", device="cpu", compute_type="int8")
    return FasterWhisperTranscriber(config=config)


def test_isolation_no_cross_imports():
    """
    Проверка инварианта изоляции модулей («Чёрные ящики»):
    - Внутри audio_preprocessing/ нет импортов из stt.
    - Внутри stt/ нет импортов из audio_preprocessing или vad.
    - Внутри vad/ нет импортов из stt или audio_preprocessing.
    """
    def get_imported_modules(root_dir: Path) -> Set[str]:
        imported: Set[str] = set()
        for py_file in root_dir.rglob("*.py"):
            with open(py_file, "r", encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read(), filename=str(py_file))
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported.add(node.module.split(".")[0])
        return imported

    prep_imports = get_imported_modules(REPO_ROOT / "audio_preprocessing")
    stt_imports = get_imported_modules(REPO_ROOT / "stt")
    vad_imports = get_imported_modules(REPO_ROOT / "vad")

    assert "stt" not in prep_imports, (
        f"Нарушение изоляции: audio_preprocessing импортирует stt! {prep_imports}"
    )

    assert "audio_preprocessing" not in stt_imports, (
        f"Нарушение изоляции: stt импортирует audio_preprocessing! {stt_imports}"
    )
    assert "vad" not in stt_imports, (
        f"Нарушение изоляции: stt импортирует vad! {stt_imports}"
    )

    assert "stt" not in vad_imports, (
        f"Нарушение изоляции: vad импортирует stt! {vad_imports}"
    )
    assert "audio_preprocessing" not in vad_imports, (
        f"Нарушение изоляции: vad импортирует audio_preprocessing! {vad_imports}"
    )


def test_orchestrator_with_preprocessing_enabled(tiny_transcriber: FasterWhisperTranscriber):
    """
    Тест композиции: LocalMockAudioLoader + AudioPreprocessVADPipeline + FasterWhisperTranscriber.
    Предобработка включена:
    - Аудио очищается, тишина вырезается
    - В STT передается только speech_only_audio
    - Таймкоды восстанавливаются на шкалу исходного аудио
    """
    assert REAL_AUDIO_FILE.is_file(), f"Тестовый файл не найден: {REAL_AUDIO_FILE}"

    loader = LocalMockAudioLoader(base_dir=REPO_ROOT)
    preprocessor = get_audio_pipeline()

    pipeline = CallProcessingPipeline(
        audio_loader=loader,
        preprocessor=preprocessor,
        transcriber=tiny_transcriber,
        remap_timestamps=True,
    )

    result = pipeline.run(REAL_AUDIO_FILE, language="ru")

    assert isinstance(result, TranscriptionResult)
    assert len(result.text.strip()) > 0
    assert len(result.segments) > 0
    assert result.duration > 30.0  # Исходная длина аудио ~35 сек

    for seg in result.segments:
        assert isinstance(seg, TranscriptionSegment)
        assert 0.0 <= seg.start <= seg.end <= result.duration + 0.5
        assert len(seg.text) > 0


def test_orchestrator_with_preprocessing_disabled(tiny_transcriber: FasterWhisperTranscriber):
    """
    Тест композиции: LocalMockAudioLoader + None + FasterWhisperTranscriber.
    Предобработка выключена:
    - Сырое аудио направляется напрямую в STT
    - STT возвращает результат без ремаппинга таймкодов
    """
    assert REAL_AUDIO_FILE.is_file(), f"Тестовый файл не найден: {REAL_AUDIO_FILE}"

    loader = LocalMockAudioLoader(base_dir=REPO_ROOT)

    pipeline = CallProcessingPipeline(
        audio_loader=loader,
        preprocessor=None,  # Выключено
        transcriber=tiny_transcriber,
        remap_timestamps=False,
    )

    result = pipeline.run(REAL_AUDIO_FILE, language="ru")

    assert isinstance(result, TranscriptionResult)
    assert len(result.text.strip()) > 0
    assert len(result.segments) > 0
    assert result.duration > 0.0


def test_orchestrator_via_rest_api_clients(tiny_transcriber: FasterWhisperTranscriber):
    """
    Тест работы CallProcessingPipeline через сетевые REST API клиенты:
    RestPreprocessorClient и RestTranscriberClient поверх FastAPI TestClient.
    """
    assert REAL_AUDIO_FILE.is_file(), f"Тестовый файл не найден: {REAL_AUDIO_FILE}"

    # Переопределяем сервис STT в FastAPI на легкий tiny инстанс для быстроты теста
    stt_app.dependency_overrides[get_stt_service] = lambda: tiny_transcriber

    try:
        with TestClient(prep_app) as prep_client, TestClient(stt_app) as stt_client:
            rest_preprocessor = RestPreprocessorClient(client=prep_client)
            rest_transcriber = RestTranscriberClient(client=stt_client)
            loader = LocalMockAudioLoader(base_dir=REPO_ROOT)

            pipeline = CallProcessingPipeline(
                audio_loader=loader,
                preprocessor=rest_preprocessor,
                transcriber=rest_transcriber,
                remap_timestamps=True,
            )

            result = pipeline.run(REAL_AUDIO_FILE, language="ru")

            assert isinstance(result, TranscriptionResult)
            assert len(result.text.strip()) > 0
            assert len(result.segments) > 0
            assert result.duration > 30.0

            for seg in result.segments:
                assert isinstance(seg, TranscriptionSegment)
                assert 0.0 <= seg.start <= seg.end <= result.duration + 0.5
    finally:
        stt_app.dependency_overrides.clear()


def test_remap_time_and_transcription_result():
    """
    Модульный тест математической точности remap_time_to_original и remap_transcription_result.
    """
    segments = [
        {"start": 2.0, "end": 5.0},
        {"start": 10.0, "end": 15.0},
    ]

    # Начало первого речевого сегмента
    assert remap_time_to_original(0.0, segments) == 2.0
    # Конец первого сегмента
    assert remap_time_to_original(3.0, segments, is_end=True) == 5.0
    # Начало второго сегмента
    assert remap_time_to_original(3.0, segments, is_end=False) == 10.0
    # Середина второго сегмента
    assert remap_time_to_original(4.5, segments) == 11.5
    # Конец второго сегмента
    assert remap_time_to_original(8.0, segments, is_end=True) == 15.0

    raw_result = TranscriptionResult(
        text="Тестовая фраза",
        language="ru",
        language_probability=0.99,
        duration=8.0,
        segments=[
            TranscriptionSegment(
                id=0,
                start=0.5,
                end=2.5,
                text="Тестовая",
                avg_logprob=-0.2,
                no_speech_prob=0.01,
            ),
            TranscriptionSegment(
                id=1,
                start=3.5,
                end=7.5,
                text="фраза",
                avg_logprob=-0.1,
                no_speech_prob=0.02,
            ),
        ],
    )

    remapped = remap_transcription_result(raw_result, segments, original_duration=20.0)
    assert remapped.duration == 20.0
    assert len(remapped.segments) == 2
    assert remapped.segments[0].start == 2.5
    assert remapped.segments[0].end == 4.5
    assert remapped.segments[1].start == 10.5
    assert remapped.segments[1].end == 14.5


def test_loader_file_not_found():
    """Проверка возбуждения FileNotFoundError при отсутствии файла."""
    loader = LocalMockAudioLoader(base_dir=REPO_ROOT)
    with pytest.raises(FileNotFoundError):
        loader.load("non_existent_call_12345.mp3")


def test_rest_preprocessor_normalizes_sample_rate():
    import base64
    import io
    import httpx
    import numpy as np
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(8000, dtype=np.float32), 8000, format="WAV")
    payload = {
        "audio_wav_base64": base64.b64encode(buffer.getvalue()).decode(),
        "speech_segments": [{"start": 0.0, "end": 1.0}],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport, base_url="http://test") as client:
        preprocessor = RestPreprocessorClient(client=client)
        audio, segments = preprocessor.process(np.zeros(16000, dtype=np.float32))
    assert audio.shape == (16000,)
    assert segments == payload["speech_segments"]
