import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
import httpx
import numpy as np
import pytest
import soundfile as sf

import audio_http
from audio_preprocessing.converters import TorchAudioConverter


def test_shared_path_rejects_escape_and_output_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "shared"
    root.mkdir()
    outside = tmp_path / "outside.wav"
    outside.touch()
    (root / "alias.wav").symlink_to(outside)
    monkeypatch.setenv("AUDIO_SHARED_ROOT", str(root))
    monkeypatch.setenv("AUDIO_SHARED_TOKEN", "test-token")

    with pytest.raises(HTTPException) as error:
        audio_http.require_shared_access()
    assert error.value.status_code == 401

    audio_http.require_shared_access("Bearer test-token")
    for output in (False, True):
        with pytest.raises(HTTPException) as error:
            audio_http.shared_path("alias.wav", {".wav"}, output=output)
        assert error.value.status_code == 403


def test_chunked_multipart_body_limit(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.add_middleware(audio_http.AudioUploadLimit)
    monkeypatch.setattr(audio_http, "MAX_UPLOAD_BYTES", 10)

    @app.post("/upload")
    async def upload(file: UploadFile):
        pytest.fail("Превысивший лимит запрос дошёл до обработчика")

    async def request():
        async def body():
            yield b"--foo\r\n"
            yield b"x" * 100

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/upload", content=body(), headers={"Content-Type": "multipart/form-data; boundary=foo"}
            )
        assert response.status_code == 413

    asyncio.run(request())


def test_small_wav_with_expensive_sample_rate_is_rejected(tmp_path: Path):
    source = tmp_path / "rare-rate.wav"
    sf.write(source, np.zeros(160, dtype=np.float32), 47999)

    with pytest.raises(ValueError, match="Слишком дорогая комбинация"):
        TorchAudioConverter().convert(source)


def test_output_is_published_without_overwriting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from audio_preprocessing.api import PreprocessByPathRequest, preprocess_by_path
    from audio_preprocessing.pipeline import AudioPipelineConfig, get_audio_pipeline

    monkeypatch.setenv("AUDIO_SHARED_ROOT", str(tmp_path))
    sf.write(tmp_path / "input.wav", np.zeros(160, dtype=np.float32), 16000)
    pipeline = get_audio_pipeline(AudioPipelineConfig(denoiser=None, vad=None))
    request = PreprocessByPathRequest(file_path="input.wav", output_wav_path="output.wav")
    preprocess_by_path(request, pipeline)
    original = (tmp_path / "output.wav").read_bytes()
    with pytest.raises(HTTPException) as error:
        preprocess_by_path(request, pipeline)
    assert error.value.status_code == 409
    assert (tmp_path / "output.wav").read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.wav", "output.wav"]


def test_vad_concurrent_calls_match_sequential_results():
    from concurrent.futures import ThreadPoolExecutor
    from vad import SileroVADAdapter

    source = Path(__file__).resolve().parents[2] / "vad" / "benchmark_reference.wav"
    audio, sample_rate = sf.read(source, dtype="float32")
    inputs = [np.roll(audio[:160000], shift) for shift in (0, 8000, 16000, 32000)]
    vad = SileroVADAdapter()
    expected = [vad.process(audio, sample_rate)[1] for audio in inputs]
    with ThreadPoolExecutor(4) as workers:
        actual = list(workers.map(lambda audio: vad.process(audio, sample_rate)[1], inputs))
    assert actual == expected


def test_silence_and_short_audio_produce_no_speech():
    from audio_preprocessing.pipeline import get_audio_pipeline
    from vad import EnergyVADAdapter, SileroVADAdapter, WebRTCVADAdapter

    silence = np.zeros(32000, dtype=np.float32)
    for vad in (EnergyVADAdapter(), SileroVADAdapter(), WebRTCVADAdapter()):
        audio, segments = vad.process(silence)
        assert audio.size == 0
        assert segments == []
    assert get_audio_pipeline().process_detailed(silence[:160]).speech_segments == []


def test_decoded_audio_volume_is_limited(tmp_path: Path):
    from audio_http import PyAVInputValidator

    source = tmp_path / "silence.flac"
    sf.write(source, np.zeros(16000, dtype=np.float32), 16000)
    with pytest.raises(HTTPException) as error:
        PyAVInputValidator(max_samples=1000).validate(source)
    assert error.value.status_code == 413

    with pytest.raises(HTTPException) as error:
        PyAVInputValidator(max_seconds=0.01).validate(source)
    assert error.value.status_code == 413

    PyAVInputValidator().validate(source)


def test_http_concurrency_limit_releases_capacity():
    app = FastAPI()
    app.add_middleware(audio_http.AudioUploadLimit)

    async def scenario():
        gate = asyncio.Event()
        ready = asyncio.Event()
        entered = 0

        @app.post("/wait")
        async def wait():
            nonlocal entered
            entered += 1
            if entered == 2:
                ready.set()
            await gate.wait()
            return {}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            requests = [asyncio.create_task(client.post("/wait")) for _ in range(2)]
            try:
                await asyncio.wait_for(ready.wait(), timeout=5)
                assert (await client.post("/wait")).status_code == 503
            finally:
                gate.set()
                responses = await asyncio.gather(*requests)
            assert all(response.status_code == 200 for response in responses)
            assert (await client.post("/wait")).status_code == 200

    asyncio.run(scenario())
