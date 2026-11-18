"""
Интеграционные и модульные тесты для пакета stt (Speech-to-Text).
Проверяют соответствие Definition of Done (DoD), контракты данных Pydantic v2,
работу с 3 реальными аудиофайлами, поддержку numpy.ndarray и graceful fallback на CPU.
"""

from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf

from stt import (
    BaseTranscriber,
    FasterWhisperTranscriber,
    TranscriberConfig,
    TranscriptionResult,
    TranscriptionSegment,
    get_transcriber,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def audio_files() -> list[Path]:
    """Список 3 реальных аудиофайлов из репозитория."""
    files = [
        REPO_ROOT / "audio_preprocessing" / "input_test_call.mp3",
        REPO_ROOT / "samples" / "test_call_youtube.mp3",
        REPO_ROOT
        / "samples"
        / "AxonData"
        / "russian-speech-recognition-dataset"
        / "Call center data samples RU"
        / "1756465406.16342 (RU Pharma Sale)"
        / "1756465406.16342.mp3",
    ]
    for f in files:
        assert f.is_file(), f"Аудиофайл не найден: {f}"
    return files


@pytest.fixture(scope="session")
def tiny_transcriber() -> BaseTranscriber:
    """Транскрибатор с моделью 'tiny' для быстрых детерминированных тестов."""
    config = TranscriberConfig(model_size="tiny", device="cuda")
    return get_transcriber(config=config)


@pytest.fixture(scope="session")
def default_transcriber() -> BaseTranscriber:
    """Транскрибатор с моделью по умолчанию."""
    config = TranscriberConfig(device="cuda")
    return get_transcriber(config=config)


def test_factory_creation():
    """Проверка фабрики get_transcriber и обработки неизвестного движка."""
    transcriber = get_transcriber("faster-whisper")
    assert isinstance(transcriber, FasterWhisperTranscriber)
    assert isinstance(transcriber, BaseTranscriber)
    assert "faster-whisper" in transcriber.name

    with pytest.raises(ValueError, match="Неизвестный STT движок"):
        get_transcriber("unsupported_engine")


def test_cuda_graceful_fallback_without_gpu(monkeypatch: pytest.MonkeyPatch):
    """
    Проверка graceful fallback:
    Запрос device='cuda' в среде без GPU (ctranslate2.get_cuda_device_count() == 0)
    должен автоматически переключиться на 'cpu' с compute_type='int8' и успешно инициализировать модель.
    """
    import ctranslate2

    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)

    config = TranscriberConfig(model_size="tiny", device="cuda", compute_type="float16")
    transcriber = FasterWhisperTranscriber(config=config)

    assert transcriber.actual_device == "cpu"
    assert transcriber.actual_compute_type == "int8"


def test_transcribe_three_real_files(
    tiny_transcriber: BaseTranscriber,
    audio_files: list[Path],
):
    """
    Тест контракта на 3 реальных аудиофайлах (DoD):
    1. Результат является экземпляром TranscriptionResult.
    2. result.text не пустой (len(result.text.strip()) > 0).
    3. len(result.segments) > 0.
    4. Для каждого сегмента: seg.start <= seg.end и len(seg.text) > 0.
    5. result.language == 'ru'.
    """
    assert len(audio_files) == 3

    for audio_path in audio_files:
        # Проверяем передачу как строкового пути
        result = tiny_transcriber.transcribe(str(audio_path))

        # Ассерт 1: Экземпляр TranscriptionResult
        assert isinstance(result, TranscriptionResult)

        # Ассерт 2: Текст не пустой
        assert len(result.text.strip()) > 0, f"Пустой текст для файла {audio_path.name}"

        # Ассерт 3: Список сегментов не пустой
        assert len(result.segments) > 0, f"Нет сегментов для файла {audio_path.name}"

        # Ассерт 4: Корректность каждого сегмента
        for seg in result.segments:
            assert isinstance(seg, TranscriptionSegment)
            assert seg.start <= seg.end, f"Некорректный интервал: {seg.start} > {seg.end}"
            assert len(seg.text) > 0, "Текст сегмента пустой"
            assert isinstance(seg.avg_logprob, float)
            assert isinstance(seg.no_speech_prob, float)

        # Ассерт 5: Язык русский
        assert result.language == "ru", f"Ожидался русский язык, получен {result.language}"

        # Дополнительная проверка метаданных
        assert result.duration > 0
        assert result.language_probability > 0.5


def test_transcribe_numpy_array(tiny_transcriber: BaseTranscriber):
    """
    Тест передачи стандартизированного numpy.ndarray (16kHz float32, выход модуля VAD).
    """
    ref_audio = REPO_ROOT / "audio_preprocessing" / "input_test_call.mp3"
    audio_data, sr = sf.read(str(ref_audio), dtype="float32")

    # Если стерео — берем моно
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)

    # Берем первые 10 секунд для быстрого теста
    slice_10s = audio_data[: int(sr * 10)]

    result = tiny_transcriber.transcribe(slice_10s)

    assert isinstance(result, TranscriptionResult)
    assert len(result.text.strip()) > 0
    assert len(result.segments) > 0
    assert result.language == "ru"
    assert result.duration > 0


def test_transcribe_path_object(tiny_transcriber: BaseTranscriber, audio_files: list[Path]):
    """Проверка передачи объекта pathlib.Path."""
    path_obj = audio_files[0]
    result = tiny_transcriber.transcribe(path_obj)
    assert isinstance(result, TranscriptionResult)
    assert len(result.text.strip()) > 0


def test_file_not_found(tiny_transcriber: BaseTranscriber):
    """Проверка генерации FileNotFoundError при передаче несуществующего пути."""
    with pytest.raises(FileNotFoundError):
        tiny_transcriber.transcribe("non_existent_audio_file.wav")


def test_invalid_audio_type(tiny_transcriber: BaseTranscriber):
    """Проверка генерации TypeError при передаче некорректного типа данных."""
    with pytest.raises(TypeError, match="Неподдерживаемый тип аудио"):
        tiny_transcriber.transcribe(12345)  # type: ignore


def test_default_model_transcription(default_transcriber: BaseTranscriber, audio_files: list[Path]):
    """Проверка транскрибации первого файла моделью по умолчанию."""
    assert default_transcriber.name == "faster-whisper-large-v3-turbo"
    result = default_transcriber.transcribe(audio_files[0])
    assert isinstance(result, TranscriptionResult)
    assert len(result.text.strip()) > 0
    assert result.language == "ru"
    assert len(result.segments) > 0


def test_recovery_fills_speech_gap_with_original_timestamps(monkeypatch: pytest.MonkeyPatch):
    def segment(*words: tuple[float, float, str]) -> SimpleNamespace:
        return SimpleNamespace(
            id=1, start=words[0][0], end=words[-1][1], avg_logprob=-0.2, no_speech_prob=0.01,
            text=" ".join(word for _, _, word in words),
            words=[SimpleNamespace(start=start, end=end, word=word, probability=0.9)
                   for start, end, word in words],
        )

    class Model:
        def transcribe(self, audio: np.ndarray, **options: object):
            assert options["word_timestamps"] is True
            if len(audio) == 15 * 16000:
                output = segment((5.2, 5.5, "Это"), (9.2, 9.5, "фразы."))
            else:
                assert len(audio) == round((13.2 - 1.5) * 16000)
                assert options["vad_filter"] is False
                output = segment(
                    (3.7, 4.0, "Это"), (4.6, 5.1, "просто"),
                    (5.4, 6.0, "середина"), (6.5, 7.1, "длинной"), (7.6, 7.8, "фразы."),
                )
            return iter([output]), SimpleNamespace(duration=15.0, language="ru", language_probability=1.0)

    monkeypatch.setattr("stt.transcriber.WhisperModel", lambda **options: Model())
    monkeypatch.setattr("stt.transcriber.get_speech_timestamps", lambda audio: [{"start": 80000, "end": 152000}])

    transcriber = get_transcriber(config=TranscriberConfig(device="cpu", compute_type="int8"))
    result = transcriber.transcribe(np.zeros(15 * 16000, dtype=np.float32), vad_filter=True)

    assert result.text == "Это просто середина длинной фразы."
    assert result.segments[1].words[0].start == 6.1
    assert [line.model_dump() for line in result.utterances] == [
        {"start": 5.2, "end": 9.5, "text": result.text},
    ]
