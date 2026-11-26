"""Проверяем различия режимов через HTTP без загрузки моделей."""

import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from demo import app as demo_app
from demo.variants import load_variants
from stt.interfaces import BaseTranscriber, TranscriptionResult


class RecordingTranscriber(BaseTranscriber):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    @property
    def name(self) -> str:
        return "recording"

    def transcribe(self, audio: str | Path | np.ndarray, **kwargs: object) -> TranscriptionResult:
        self.calls.append(kwargs)
        return TranscriptionResult(text="", language="ru", language_probability=1.0, duration=1)


def wav_bytes() -> bytes:
    output = BytesIO()
    sf.write(output, np.zeros(1600, dtype=np.float32), 16000, format="WAV")
    return output.getvalue()


def test_presets_match_benchmark_and_reach_model(monkeypatch: pytest.MonkeyPatch) -> None:
    whisper = RecordingTranscriber()
    tone = RecordingTranscriber()
    monkeypatch.setattr(demo_app, "get_stt_service", lambda: whisper)
    monkeypatch.setattr(demo_app, "get_tone_service", lambda: tone)
    benchmark = json.loads(Path("stt/benchmark_variants.json").read_text(encoding="utf-8"))
    expected = {item["name"]: item["options"] for item in benchmark}
    with TestClient(demo_app.app) as client:
        variants = client.get("/api/variants").json()
        assert {variant["id"] for variant in variants} == {
            "current_recovery", "vad_5s", "vad_5s_sensitive", "vad_5s_beam1", "full_audio", "tone",
        }
        for variant in variants:
            response = client.post(f"/api/transcribe/{variant['id']}",
                                   files={"file": ("call.wav", wav_bytes(), "audio/wav")})
            assert response.status_code == 200, response.text
            assert response.json()["elapsed_s"] >= 0
            assert response.json()["transcript"]["language"] == "ru"
            calls = tone.calls if variant["id"] == "tone" else whisper.calls
            options = calls[-1]
            if variant["id"] != "tone":
                assert options == {
                    "language": "ru", "beam_size": 5, "vad_filter": True,
                    "condition_on_previous_text": False, "initial_prompt": None,
                    "word_timestamps": True, "recover_missing_speech": False,
                    **expected[variant["id"]],
                }
        assert len(whisper.calls) == 5
        assert len(tone.calls) == 1


def test_failed_variant_does_not_block_next(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> BaseTranscriber:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(demo_app, "get_tone_service", fail)
    monkeypatch.setattr(demo_app, "get_stt_service", RecordingTranscriber)
    with TestClient(demo_app.app) as client:
        assert client.post("/api/transcribe/unknown", files={"file": ("x.wav", wav_bytes())}).status_code == 404
        assert client.post("/api/transcribe/tone", files={"file": ("x.wav", wav_bytes())}).status_code == 503
        assert client.post("/api/transcribe/full_audio", files={"file": ("x.wav", wav_bytes())}).status_code == 200
        assert client.post("/api/transcribe/full_audio", files={"file": ("x.exe", b"bad")}).status_code == 400


def test_custom_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "variants.json"
    preset = {"id": "custom", "label": "Свой режим", "description": "Без VAD",
              "engine": "whisper", "options": {"vad_filter": False}}
    config.write_text(json.dumps([preset]), encoding="utf-8")
    monkeypatch.setenv("DEMO_VARIANTS_CONFIG", str(config))
    assert load_variants()[0].id == "custom"
    config.write_text(json.dumps([preset, preset]), encoding="utf-8")
    with pytest.raises(ValueError, match="уникальными"):
        load_variants()
