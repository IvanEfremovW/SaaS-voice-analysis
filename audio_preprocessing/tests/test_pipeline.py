"""
Интеграционные и модульные тесты для единого конвейера Preprocess + VAD (Issue #5, Issue #6).
Проверяют:
1. Создание продакшн-стека по умолчанию (torchaudio + stat_spectral + silero).
2. Фабрики get_converter, get_denoiser, get_vad и обработку недопустимых имен.
3. Прогон конвейера на 3 реальных аудиофайлах датасета (zero-disk I/O, float32, VAD).
4. Математическую точность утилиты восстановления таймкодов (remap_time_to_original).
5. Сквозной пайплайн: AudioPreprocessVADPipeline -> FasterWhisperTranscriber -> remap_transcription_result.
"""

from pathlib import Path
from typing import List
import numpy as np
import pytest

from audio_preprocessing import (
    AudioPipelineConfig,
    AudioPipelineResult,
    AudioPreprocessVADPipeline,
    FFmpegConverter,
    LibrosaConverter,
    NonStationarySpectralDenoiser,
    StationarySpectralDenoiser,
    TelephonyBandpassDenoiser,
    TorchAudioConverter,
    get_audio_pipeline,
    get_converter,
    get_denoiser,
    remap_time_to_original,
    remap_transcription_result,
)
from stt import FasterWhisperTranscriber, TranscriberConfig, get_transcriber
from stt.interfaces import TranscriptionResult, TranscriptionSegment
from vad import EnergyVADAdapter, SileroVADAdapter, WebRTCVADAdapter, get_vad

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def audio_files() -> List[Path]:
    """Список из трех реальных аудиофайлов разного формата и происхождения."""
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


def test_default_production_stack():
    """
    Проверка утвержденного техлидом продакшн-стека по умолчанию:
    TorchAudioConverter + StationarySpectralDenoiser + SileroVADAdapter (threshold=0.5).
    """
    config = AudioPipelineConfig()
    assert config.target_sr == 16000
    assert config.converter == "torchaudio"
    assert config.denoiser == "stat_spectral"
    assert config.vad == "silero"

    pipeline = AudioPreprocessVADPipeline()
    assert isinstance(pipeline.converter, TorchAudioConverter)
    assert pipeline.converter.name == "torchaudio"

    assert isinstance(pipeline.denoiser, StationarySpectralDenoiser)
    assert pipeline.denoiser.name == "stat_spectral"
    assert pipeline.denoiser.prop_decrease == 0.85
    assert pipeline.denoiser.normalize is True

    assert isinstance(pipeline.vad, SileroVADAdapter)
    assert pipeline.vad.name == "silero"
    assert pipeline.vad.threshold == 0.5

    # Проверка создания через фабрику get_audio_pipeline
    pipeline_factory = get_audio_pipeline()
    assert isinstance(pipeline_factory, AudioPreprocessVADPipeline)
    assert pipeline_factory.converter.name == "torchaudio"
    assert pipeline_factory.denoiser.name == "stat_spectral"
    assert pipeline_factory.vad.name == "silero"


def test_factories_and_invalid_names():
    """
    Проверка фабрик компонентов:
    - Все варианты адаптеров (converters, denoisers, vads)
    - Режимы отключения ('none', None)
    - Выброс ValueError на неизвестные имена и некорректные типы.
    """
    # 1. Converters
    assert isinstance(get_converter("torchaudio"), TorchAudioConverter)
    assert isinstance(get_converter("ffmpeg"), FFmpegConverter)
    assert isinstance(get_converter("librosa"), LibrosaConverter)

    with pytest.raises(ValueError, match="Неизвестный конвертер"):
        get_converter("unknown_conv")

    with pytest.raises(ValueError, match="Имя конвертера должно быть строкой"):
        get_converter(12345)  # type: ignore

    # 2. Denoisers
    assert isinstance(get_denoiser("stat_spectral"), StationarySpectralDenoiser)
    assert isinstance(get_denoiser("nonstat_spectral"), NonStationarySpectralDenoiser)
    assert isinstance(get_denoiser("telephony_bandpass"), TelephonyBandpassDenoiser)
    assert get_denoiser("none") is None
    assert get_denoiser("None") is None
    assert get_denoiser(None) is None

    with pytest.raises(ValueError, match="Неизвестный алгоритм шумоподавления"):
        get_denoiser("unsupported_denoiser")

    with pytest.raises(ValueError, match="Имя шумодава должно быть строкой"):
        get_denoiser(999)  # type: ignore

    # 3. VADs
    assert isinstance(get_vad("silero"), SileroVADAdapter)
    assert isinstance(get_vad("webrtc"), WebRTCVADAdapter)
    assert isinstance(get_vad("energy"), EnergyVADAdapter)
    assert get_vad("none") is None
    assert get_vad("None") is None
    assert get_vad(None) is None

    with pytest.raises(ValueError, match="Неизвестный VAD алгоритм"):
        get_vad("unsupported_vad")

    with pytest.raises(ValueError, match="Имя VAD должно быть строкой"):
        get_vad(777)  # type: ignore

    # 4. Pipeline с отключенным VAD и шумодавом
    bypass_config = AudioPipelineConfig(denoiser=None, vad="none")
    bypass_pipeline = get_audio_pipeline(bypass_config)
    assert bypass_pipeline.denoiser is None
    assert bypass_pipeline.vad is None


def test_pipeline_on_three_real_files(audio_files: List[Path]):
    """
    Прогон AudioPreprocessVADPipeline на трех реальных аудиофайлах датасета:
    - Проверка типа возвращаемого AudioPipelineResult
    - Проверка 1D float32 моно
    - Проверка непустых speech_segments
    - Проверка соотношения длительностей 0 < speech_duration <= original_duration
    - Проверка совпадения выходов process() и process_detailed()
    """
    pipeline = get_audio_pipeline()

    for audio_path in audio_files:
        # 1. Детальный запуск в памяти
        result = pipeline.process_detailed(audio_path)

        assert isinstance(result, AudioPipelineResult)
        assert isinstance(result.speech_only_audio, np.ndarray)
        assert result.speech_only_audio.dtype == np.float32
        assert result.speech_only_audio.ndim == 1
        assert result.sample_rate == 16000

        # Длительности и удержание
        assert result.original_duration > 0.0
        assert 0.0 < result.speech_duration <= result.original_duration + 0.05
        assert 0.0 < result.retention_pct <= 100.0

        # Сегменты речи
        assert len(result.speech_segments) > 0
        for seg in result.speech_segments:
            assert "start" in seg and "end" in seg
            assert 0.0 <= seg["start"] <= seg["end"]
            assert seg["end"] <= result.original_duration + 0.1

        # 2. Проверка метода process() (кортеж аудио и сегментов)
        compact_audio, segments = pipeline.process(audio_path)
        assert np.array_equal(compact_audio, result.speech_only_audio)
        assert segments == result.speech_segments

        # 3. Проверка передачи np.ndarray в пайплайн
        np_result = pipeline.process_detailed(result.speech_only_audio, sr=16000)
        assert isinstance(np_result, AudioPipelineResult)
        assert np_result.speech_only_audio.dtype == np.float32
        assert np_result.speech_only_audio.ndim == 1


def test_remap_time_to_original():
    """
    Проверка математической точности пересчета таймкодов со склеенного аудио
    на исходную шкалу времени:
    Сегменты: [{'start': 2.0, 'end': 5.0}, {'start': 10.0, 'end': 15.0}]
    - compact_time: 0.0 -> original: 2.0
    - compact_time: 3.0 -> original: 5.0 / 10.0
    - compact_time: 4.5 -> original: 11.5
    - compact_time: 8.0 -> original: 15.0
    """
    segments = [
        {"start": 2.0, "end": 5.0},
        {"start": 10.0, "end": 15.0},
    ]

    # Начало первого речевого сегмента
    assert remap_time_to_original(0.0, segments) == 2.0

    # Граница между сегментами:
    # 3.0 может интерпретироваться и как конец seg0 (5.0), и как начало seg1 (10.0)
    boundary_val = remap_time_to_original(3.0, segments)
    assert boundary_val in (5.0, 10.0)
    assert remap_time_to_original(3.0, segments, is_end=False) == 10.0
    assert remap_time_to_original(3.0, segments, is_end=True) == 5.0

    # Середина второго сегмента: 3.0 (длина seg0) + 1.5 = 4.5 -> 10.0 + 1.5 = 11.5
    assert remap_time_to_original(4.5, segments) == 11.5

    # Конец второго сегмента: 3.0 + 5.0 = 8.0 -> 15.0
    assert remap_time_to_original(8.0, segments, is_end=True) == 15.0

    # Краевые значения:
    # Отрицательное время -> прижимается к началу первого сегмента
    assert remap_time_to_original(-1.0, segments) == 2.0
    # Время за пределами суммы сегментов -> прижимается к концу последнего сегмента
    assert remap_time_to_original(20.0, segments) == 15.0
    # Пустой список сегментов
    assert remap_time_to_original(3.14, []) == 3.14

    # Тестирование remap_transcription_result
    raw_stt = TranscriptionResult(
        text="Здравствуйте, это отдел контроля качества.",
        language="ru",
        language_probability=0.99,
        duration=8.0,
        segments=[
            TranscriptionSegment(
                id=0,
                start=0.5,
                end=2.5,
                text="Здравствуйте,",
                avg_logprob=-0.15,
                no_speech_prob=0.01,
            ),
            TranscriptionSegment(
                id=1,
                start=3.5,
                end=7.5,
                text="это отдел контроля качества.",
                avg_logprob=-0.12,
                no_speech_prob=0.02,
            ),
        ],
    )

    remapped = remap_transcription_result(raw_stt, segments, original_duration=18.0)
    assert isinstance(remapped, TranscriptionResult)
    assert remapped.duration == 18.0
    assert len(remapped.segments) == 2

    # Сегмент 0: [0.5, 2.5] внутри [0.0, 3.0] -> [2.0 + 0.5, 2.0 + 2.5] = [2.5, 4.5]
    assert remapped.segments[0].start == 2.5
    assert remapped.segments[0].end == 4.5
    assert remapped.segments[0].text == "Здравствуйте,"

    # Сегмент 1: [3.5, 7.5] внутри [3.0, 8.0] -> [10.0 + 0.5, 10.0 + 4.5] = [10.5, 14.5]
    assert remapped.segments[1].start == 10.5
    assert remapped.segments[1].end == 14.5
    assert remapped.segments[1].text == "это отдел контроля качества."


def test_end_to_end_preprocess_vad_stt():
    """
    Сквозной интеграционный тест полного конвейера в оперативной памяти (Zero-disk I/O):
    AudioPreprocessVADPipeline -> FasterWhisperTranscriber (tiny) -> remap_transcription_result.
    """
    ref_audio = REPO_ROOT / "audio_preprocessing" / "input_test_call.mp3"
    assert ref_audio.is_file()

    # 1. Предобработка + VAD
    pipeline = get_audio_pipeline()
    pipeline_res = pipeline.process_detailed(ref_audio)

    assert pipeline_res.speech_only_audio.dtype == np.float32
    assert len(pipeline_res.speech_segments) > 0

    # 2. Транскрибация компактного речевого аудио Whisper (модель tiny на CPU)
    stt_config = TranscriberConfig(model_size="tiny", device="cpu", compute_type="int8")
    transcriber = FasterWhisperTranscriber(config=stt_config)

    raw_stt_result = transcriber.transcribe(pipeline_res.speech_only_audio)
    assert isinstance(raw_stt_result, TranscriptionResult)
    assert len(raw_stt_result.text.strip()) > 0
    assert len(raw_stt_result.segments) > 0

    # 3. Восстановление таймкодов на исходный хронометраж
    final_result = remap_transcription_result(
        result=raw_stt_result,
        speech_segments=pipeline_res.speech_segments,
        original_duration=pipeline_res.original_duration,
    )

    assert isinstance(final_result, TranscriptionResult)
    assert final_result.duration == pipeline_res.original_duration
    assert len(final_result.segments) == len(raw_stt_result.segments)
    assert final_result.text == raw_stt_result.text

    # Проверка, что все сегменты попали в границы исходного аудио
    for seg in final_result.segments:
        assert 0.0 <= seg.start <= seg.end <= pipeline_res.original_duration + 0.5
        assert len(seg.text) > 0
