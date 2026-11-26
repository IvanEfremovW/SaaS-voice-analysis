import io
import time
import wave
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from audio_http import MAX_UPLOAD_BYTES, PyAVInputValidator
from orchestrator.jobs.api import create_app
from orchestrator.jobs.broker import publish_pending
from orchestrator.jobs.config import JobSettings
from orchestrator.jobs.execution import JobOutput
from orchestrator.jobs.store import LEASE_SECONDS, SQLiteJobStore
from orchestrator.jobs.worker import process_job
from stt import TranscriptionResult


class RecordedQueue:
    def __init__(self, *, available: bool = True):
        self.available = available
        self.published = []

    def publish(self, job_id):
        if not self.available:
            raise ConnectionError("RabbitMQ недоступен")
        self.published.append(job_id)


@pytest.fixture
def wav_bytes():
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(32000))
    return audio.getvalue()


@pytest.fixture
def settings(tmp_path):
    return JobSettings(tmp_path / "audio", tmp_path / "jobs.sqlite3", "memory://")


def get_result(client, accepted):
    return client.get(
        accepted["status_url"], headers={"Authorization": f"Bearer {accepted['access_token']}"},
    )


def wait_for_publish(queue):
    deadline = time.monotonic() + 5
    while not queue.published and time.monotonic() < deadline:
        time.sleep(0.025)
    assert queue.published


def test_http_job_survives_api_restart(settings, wav_bytes):
    queue = RecordedQueue(available=False)
    with TestClient(create_app(settings, queue=queue)) as client:
        reply = client.post("/api/v1/jobs", files={"file": ("call.wav", wav_bytes)})
        assert reply.status_code == 202
        accepted = reply.json()
        assert accepted["status"] == "queued"
        assert get_result(client, accepted).json()["status"] == "queued"
    assert not queue.published

    queue.available = True
    with TestClient(create_app(settings, queue=queue)) as client:
        wait_for_publish(queue)
        job_id = queue.published[0]
        assert str(job_id) == accepted["job_id"]
        assert client.get("/api/v1/jobs/55f0fb71-b8bb-4eba-9a57-f8c5fa60a219").status_code == 404

        def transcribe(_job_id, path: Path, _options) -> JobOutput:
            assert path.name == f"{job_id}.wav"
            assert get_result(client, accepted).json()["status"] == "running"
            return JobOutput(result=TranscriptionResult(
                text="Привет", language="ru", language_probability=1, duration=1, segments=[],
            ))

        store = SQLiteJobStore(settings.db_path)
        validator = PyAVInputValidator()
        process_job(job_id, settings.audio_dir, store, validator, transcribe)
        process_job(job_id, settings.audio_dir, store, validator, lambda *_: pytest.fail("Задание не должно выполняться"))
        job = get_result(client, accepted).json()
        assert job["status"] == "succeeded"
        assert job["result"]["text"] == "Привет"


def test_reject_invalid_audio(settings):
    with TestClient(create_app(settings, queue=RecordedQueue())) as client:
        path = "/api/v1/jobs"
        assert client.post(path, files={"file": ("call.exe", b"x")}).status_code == 415
        assert client.post(path, files={"file": ("call.wav", b"invalid")}).status_code == 400
        assert client.post(path, files={"file": ("call.wav", bytes(MAX_UPLOAD_BYTES))}).status_code == 413
    assert list(settings.audio_dir.iterdir()) == []


def test_failed_publish_keeps_job_pending(settings):
    store = SQLiteJobStore(settings.db_path)
    job_id = uuid4()
    store.create(job_id, "call.wav")
    with pytest.raises(ConnectionError):
        publish_pending(store, RecordedQueue(available=False))
    assert store.pending() == [job_id]


def test_worker_counts_interruption_and_processing_failures(settings, wav_bytes):
    now = 1000.0
    store = SQLiteJobStore(settings.db_path, clock=lambda: now)
    job_id = uuid4()
    settings.audio_dir.mkdir()
    (settings.audio_dir / "call.wav").write_bytes(wav_bytes)
    store.create(job_id, "call.wav")
    assert store.claim(job_id).filename == "call.wav"  # Началась попытка, воркер завершился.
    now += LEASE_SECONDS + 1
    attempts = []

    def transcribe(_job_id, path, _options):
        attempts.append(path)
        raise RuntimeError("Ошибка модели")

    process_job(job_id, settings.audio_dir, store, PyAVInputValidator(), transcribe)
    assert len(attempts) == 2
    job = store.get(job_id)
    assert job.status == "failed"
    assert job.error == "Исчерпаны попытки обработки"


@pytest.mark.parametrize("invalid_file", [None, b"invalid"])
def test_unreadable_input_fails_without_inference(settings, invalid_file):
    store = SQLiteJobStore(settings.db_path)
    job_id = uuid4()
    settings.audio_dir.mkdir()
    if invalid_file is not None:
        (settings.audio_dir / "call.wav").write_bytes(invalid_file)
    store.create(job_id, "call.wav")
    process_job(job_id, settings.audio_dir, store, PyAVInputValidator(), lambda *_: pytest.fail("Задание не должно выполняться"))
    assert store.get(job_id).status == "failed"


def test_job_modes_and_variant_snapshot(settings, wav_bytes, monkeypatch):
    import numpy as np

    from audio_preprocessing import AudioPipelineResult
    from orchestrator.jobs import execution
    from stt.interfaces import TranscriptionSegment, TranscriptionWord
    from stt.variants import load_variants, variant_options

    queue = RecordedQueue(available=False)
    speech = np.ones(16000, dtype=np.float32)
    calls = []

    class Preprocessor:
        def process_detailed(self, audio, sr):
            calls.append(("vad", sr))
            return AudioPipelineResult(
                speech_only_audio=speech, speech_segments=[{"start": 2.0, "end": 3.0}],
                original_duration=3, speech_duration=1, retention_pct=33.33, sample_rate=sr,
            )

    class Transcriber:
        def transcribe(self, source, **options):
            calls.append(("stt", source, options))
            word = TranscriptionWord(text="Привет", start=0.1, end=0.5, probability=1)
            segment = TranscriptionSegment(
                id=1, start=0.1, end=0.5, text=word.text, avg_logprob=0, no_speech_prob=0, words=[word],
            )
            return TranscriptionResult(
                text=word.text, language="ru", language_probability=1, duration=1, segments=[segment],
            )

    monkeypatch.setattr(execution, "get_preprocessor", lambda vad: Preprocessor())
    monkeypatch.setattr(execution, "get_job_transcriber", lambda *args: Transcriber())
    store = SQLiteJobStore(settings.db_path)
    with TestClient(create_app(settings, store=store, queue=queue)) as client:
        variants = client.get("/api/v1/jobs/variants").json()
        assert [variant["id"] for variant in variants] == [variant.id for variant in load_variants()]
        assert next(variant for variant in variants if variant["id"] == "tone")["supported_devices"] == ["cpu"]
        for mode in ("vad", "stt", "pipeline"):
            data = {"mode": mode}
            if mode != "vad":
                data["variant_id"] = "vad_5s_beam1"
            if mode == "pipeline":
                data["beam_size"] = "4"
            response = client.post("/api/v1/jobs", data=data, files={"file": ("call.wav", wav_bytes)})
            assert response.status_code == 202
            job_id = UUID(response.json()["job_id"])
            monkeypatch.setenv("DEMO_VARIANTS_CONFIG", str(settings.audio_dir / "missing.json"))
            process_job(job_id, settings.audio_dir, store, PyAVInputValidator())
            monkeypatch.delenv("DEMO_VARIANTS_CONFIG")
            result = get_result(client, response.json()).json()
            assert result["status"] == "succeeded"
            assert ("preprocessing" in result) == (mode != "stt")
            assert ("result" in result) == (mode != "vad")
            if mode == "stt":
                profile = next(item for item in load_variants() if item.id == "vad_5s_beam1")
                assert calls[-1][2] == variant_options(profile)
            if mode == "pipeline":
                assert calls[-1][2]["vad_filter"] is False
                assert calls[-1][2]["beam_size"] == 4
                assert result["result"]["segments"][0]["words"][0]["start"] == 2.1
        assert [call[0] for call in calls] == ["vad", "stt", "vad", "stt"]


def test_job_rejects_unsupported_options_and_unavailable_cuda(settings, wav_bytes, monkeypatch):
    monkeypatch.setattr("stt.transcriber.ctranslate2.get_cuda_device_count", lambda: 0)
    store = SQLiteJobStore(settings.db_path)
    with TestClient(create_app(settings, store=store, queue=RecordedQueue())) as client:
        for data in ({"variant_id": "missing"}, {"variant_id": "tone", "device": "gpu"}):
            response = client.post("/api/v1/jobs", data=data, files={"file": ("call.wav", wav_bytes)})
            assert response.status_code == 422
        r = client.post(
            "/api/v1/jobs", data={"mode": "stt", "device": "gpu"}, files={"file": ("call.wav", wav_bytes)},
        )
        assert r.status_code == 202
        process_job(UUID(r.json()["job_id"]), settings.audio_dir, store, PyAVInputValidator())
        assert get_result(client, r.json()).json()["error"] == "CUDA недоступна на воркере"


def test_job_by_path_protects_results_and_wav(settings, wav_bytes, tmp_path, monkeypatch):
    import base64

    monkeypatch.setenv("AUDIO_SHARED_ROOT", str(tmp_path))
    monkeypatch.setenv("AUDIO_SHARED_TOKEN", "test")
    (tmp_path / "call.wav").write_bytes(wav_bytes)
    store = SQLiteJobStore(settings.db_path)
    with TestClient(create_app(settings, store=store, queue=RecordedQueue())) as client:
        path = "/api/v1/jobs/by-path"
        body = {"file_path": "call.wav", "output_wav_path": "speech.wav", "mode": "vad",
                "vad": "energy", "include_audio_base64": True}
        auth = {"Authorization": "Bearer test"}
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, json={**body, "file_path": "../call.wav"}, headers=auth).status_code == 403
        r = client.post(path, json=body, headers=auth)
        assert r.status_code == 202
        assert client.get(r.json()["status_url"]).status_code == 401
        (tmp_path / "call.wav").unlink()
        process_job(UUID(r.json()["job_id"]), settings.audio_dir, store, PyAVInputValidator())
        job = get_result(client, r.json()).json()
        assert job["status"] == "succeeded"
        assert base64.b64decode(job["preprocessing"]["audio_wav_base64"]) == (tmp_path / "speech.wav").read_bytes()
        (tmp_path / "call.wav").write_bytes(wav_bytes)
        assert client.post(path, json=body, headers=auth).status_code == 409


def test_wav_publication_recovers_and_refuses_other_files(tmp_path):
    from orchestrator.jobs.execution import JobFailure, publish_wav

    destination = tmp_path / "speech.wav"
    job_id = uuid4()
    staged = publish_wav(job_id, destination, b"own")
    assert publish_wav(job_id, destination, b"retry") == staged
    with pytest.raises(JobFailure, match="Выходной файл уже существует"):
        publish_wav(uuid4(), destination, b"other")
    assert destination.read_bytes() == b"own"


def test_migrates_old_sqlite_job(settings, wav_bytes):
    import sqlite3

    old_id = uuid4()
    with sqlite3.connect(settings.db_path) as db:
        db.execute("""
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY, filename TEXT, status TEXT DEFAULT 'queued',
                pending INTEGER DEFAULT 1, attempts INTEGER DEFAULT 0, result TEXT, error TEXT
            )
        """)
        db.execute("INSERT INTO jobs(job_id, filename) VALUES (?, 'old.wav')", (str(old_id),))
    settings.audio_dir.mkdir()
    (settings.audio_dir / "old.wav").write_bytes(wav_bytes)
    store = SQLiteJobStore(settings.db_path)

    def execute(job_id, path, options):
        assert job_id == old_id and path.name == "old.wav" and options is None
        return JobOutput(result=TranscriptionResult(text="", language="ru", language_probability=0, duration=1))

    process_job(old_id, settings.audio_dir, store, PyAVInputValidator(), execute)
    assert store.get(old_id).status == "succeeded"


def test_job_token_is_unique_and_quota_rejects_extra_upload(settings, wav_bytes):
    from dataclasses import replace

    settings = replace(settings, max_jobs=2)
    with TestClient(create_app(settings, queue=RecordedQueue())) as client:
        def submit():
            return client.post("/api/v1/jobs", files={"file": ("call.wav", wav_bytes)})

        first, second = submit().json(), submit().json()
        assert first["access_token"] != second["access_token"]
        assert client.get(first["status_url"]).status_code == 401
        assert client.get(first["status_url"], headers={
            "Authorization": f"Bearer {second['access_token']}",
        }).status_code == 401
        assert get_result(client, first).status_code == 200
        assert submit().status_code == 507
        assert len(list(settings.audio_dir.iterdir())) == 2
        assert settings.db_path.stat().st_mode & 0o777 == 0o600


def test_claim_is_exclusive_and_expired_worker_cannot_publish(settings, wav_bytes):
    now = 1000.0
    store = SQLiteJobStore(settings.db_path, audio_dir=settings.audio_dir, retention_seconds=200, clock=lambda: now)
    settings.audio_dir.mkdir()
    source = settings.audio_dir / "call.wav"
    source.write_bytes(wav_bytes)
    job_id = uuid4()
    store.create(job_id, source.name, input_bytes=len(wav_bytes))
    first = store.claim(job_id)
    assert first is not None
    assert store.claim(job_id) is None
    now += LEASE_SECONDS - 1
    assert store.renew(job_id, first.attempt)
    now += 2
    assert store.claim(job_id) is None
    now += LEASE_SECONDS
    store.maintain()
    assert store.pending() == [job_id]
    second = store.claim(job_id)
    assert second is not None and second.attempt != first.attempt
    assert not store.finish(
        job_id, first.attempt,
        result=TranscriptionResult(text="", language="ru", language_probability=0, duration=1),
        before_commit=lambda: pytest.fail("Просроченная попытка не может публиковать WAV"),
    )
    assert store.finish(job_id, second.attempt, error="Проверочная ошибка")
    assert store.get(job_id).error == "Проверочная ошибка"
    now += 201
    store.maintain()
    assert store.get(job_id) is None
    assert not source.exists()


@pytest.mark.parametrize(("extension", "codec"), [("m4a", "aac"), ("webm", "libopus")])
def test_worker_decodes_accepted_container(settings, extension, codec):
    import av
    import numpy as np

    rate = 48000
    samples = np.zeros((1, rate), dtype=np.int16)
    contents = io.BytesIO()
    with av.open(contents, "w", format="mp4" if extension == "m4a" else extension) as output:
        stream = output.add_stream(codec, rate=rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)

    with TestClient(create_app(settings, queue=RecordedQueue())) as client:
        response = client.post(
            "/api/v1/jobs", data={"mode": "vad", "vad": "energy"},
            files={"file": (f"call.{extension}", contents.getvalue())},
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        process_job(UUID(accepted["job_id"]), settings.audio_dir, SQLiteJobStore(settings.db_path))
        result = get_result(client, accepted).json()
        assert result["status"] == "succeeded", result
        assert result["preprocessing"]["original_duration"] == pytest.approx(1.0, abs=0.06)
