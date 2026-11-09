"""
HTTP REST-клиенты для взаимодействия микросервисов в оркестраторе (паттерн Adapter).
Обеспечивают прозрачную замену in-memory классов на внешние REST API микросервисы (FastAPI).
"""

import base64
import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import httpx
import numpy as np
import soundfile as sf

from stt.interfaces import TranscriptionResult, TranscriptionSegment

logger = logging.getLogger("Orchestrator.RestClients")


class RestPreprocessorClient:
    """
    HTTP-адаптер для взаимодействия с микросервисом Audio Preprocessing & VAD (FastAPI).
    Реализует тот же интерфейс process(), что и локальный AudioPreprocessVADPipeline.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8002",
        client: Optional[Any] = None,
        timeout: float = 60.0,
    ) -> None:
        """
        :param base_url: Базовый URL микросервиса предобработки.
        :param client: Опциональный httpx.Client или TestClient (для интеграционных тестов).
        :param timeout: Таймаут запросов в секундах.
        """
        self.base_url = base_url.rstrip("/")
        self._custom_client = client
        self.timeout = timeout
        self._owned_client: Optional[httpx.Client] = None

    def _get_client(self) -> Any:
        if self._custom_client is not None:
            return self._custom_client
        if self._owned_client is None:
            self._owned_client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._owned_client

    def _url(self, path: str) -> str:
        clean_path = "/" + path.lstrip("/")
        # Если передан кастомный клиент (например TestClient), относительный путь часто предпочтителен
        if self._custom_client is not None and not str(getattr(self._custom_client, "base_url", "")).startswith("http"):
            return clean_path
        return f"{self.base_url}{clean_path}"

    def process(
        self,
        audio_source: Union[str, Path, np.ndarray],
        sr: int = 16000,
    ) -> Tuple[np.ndarray, List[Dict[str, float]]]:
        """
        Отправляет аудио на POST /api/v1/preprocess, получает Base64 WAV и речевые сегменты,
        декодирует обратно в 1D float32 numpy массив.

        :param audio_source: 1D/2D массив аудио или путь к файлу.
        :param sr: Частота дискретизации аудио (если передан массив).
        :return: Кортеж (speech_only_audio 1D float32, speech_segments [{'start': float, 'end': float}]).
        """
        client = self._get_client()
        url = self._url("/api/v1/preprocess")

        files: Dict[str, Any] = {}
        data: Dict[str, Any] = {"include_audio_base64": "true"}

        if isinstance(audio_source, (str, Path)):
            path = Path(audio_source).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Файл не найден для отправки в сервис предобработки: {path}")
            with open(path, "rb") as f:
                content = f.read()
            files = {"file": (path.name, content, "application/octet-stream")}
        elif isinstance(audio_source, np.ndarray):
            buf = io.BytesIO()
            # Экспортируем в стандартизированный 16-битный WAV
            sf.write(buf, audio_source, sr, format="WAV", subtype="PCM_16")
            buf.seek(0)
            files = {"file": ("audio_input.wav", buf.getvalue(), "audio/wav")}
        else:
            raise TypeError(f"Неподдерживаемый тип аудиоисточника: {type(audio_source)}")

        logger.debug("Отправка запроса на %s (include_audio_base64=True)", url)
        post_kwargs: Dict[str, Any] = {}
        if type(client).__name__ != "TestClient":
            post_kwargs["timeout"] = self.timeout

        resp = client.post(url, files=files, data=data, **post_kwargs)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Ошибка микросервиса предобработки ({resp.status_code}): {resp.text}"
            )

        resp_json = resp.json()
        b64_audio = resp_json.get("audio_wav_base64")
        if not b64_audio:
            raise ValueError("Микросервис предобработки не вернул поле audio_wav_base64")

        # Декодирование WAV из Base64 в 1D float32 numpy массив
        wav_bytes = base64.b64decode(b64_audio)
        speech_audio, out_sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        if out_sr != 16000 and speech_audio.size:
            from scipy.signal import resample_poly
            from math import gcd

            divisor = gcd(out_sr, 16000)
            speech_audio = resample_poly(speech_audio, 16000 // divisor, out_sr // divisor, axis=0)
        if speech_audio.ndim > 1:
            speech_audio = np.mean(speech_audio, axis=1)

        speech_segments: List[Dict[str, float]] = [
            {"start": float(seg["start"]), "end": float(seg["end"])}
            for seg in resp_json.get("speech_segments", [])
        ]

        logger.debug(
            "Ответ сервиса предобработки: сегментов=%d, speech_len=%d (sr=%d)",
            len(speech_segments),
            len(speech_audio),
            out_sr,
        )
        return speech_audio.astype(np.float32), speech_segments

    def close(self) -> None:
        if self._owned_client is not None:
            self._owned_client.close()
            self._owned_client = None

    def __enter__(self) -> "RestPreprocessorClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class RestTranscriberClient:
    """
    HTTP-адаптер для взаимодействия с микросервисом транскрибации речи STT (FastAPI).
    Реализует тот же интерфейс transcribe(), что и локальный BaseTranscriber.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        client: Optional[Any] = None,
        timeout: float = 120.0,
    ) -> None:
        """
        :param base_url: Базовый URL микросервиса транскрибации STT.
        :param client: Опциональный httpx.Client или TestClient (для интеграционных тестов).
        :param timeout: Таймаут запросов в секундах.
        """
        self.base_url = base_url.rstrip("/")
        self._custom_client = client
        self.timeout = timeout
        self._owned_client: Optional[httpx.Client] = None

    def _get_client(self) -> Any:
        if self._custom_client is not None:
            return self._custom_client
        if self._owned_client is None:
            self._owned_client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._owned_client

    def _url(self, path: str) -> str:
        clean_path = "/" + path.lstrip("/")
        if self._custom_client is not None and not str(getattr(self._custom_client, "base_url", "")).startswith("http"):
            return clean_path
        return f"{self.base_url}{clean_path}"

    def transcribe(
        self,
        audio: Union[str, Path, np.ndarray],
        **kwargs: Any,
    ) -> TranscriptionResult:
        """
        Принимает numpy массив или путь к аудио, отправляет POST /api/v1/transcribe
        и возвращает валидированный Pydantic-объект TranscriptionResult.

        :param audio: 1D float32 numpy массив (16kHz) или путь к аудиофайлу.
        :param kwargs: Параметры: language, beam_size, vad_filter, condition_on_previous_text, initial_prompt.
        :return: Валидированный TranscriptionResult.
        """
        client = self._get_client()
        url = self._url("/api/v1/transcribe")

        files: Dict[str, Any] = {}
        if isinstance(audio, (str, Path)):
            path = Path(audio).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Файл не найден для транскрибации: {path}")
            with open(path, "rb") as f:
                content = f.read()
            files = {"file": (path.name, content, "application/octet-stream")}
        elif isinstance(audio, np.ndarray):
            buf = io.BytesIO()
            sample_rate = int(kwargs.pop("sample_rate", 16000))
            sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
            buf.seek(0)
            files = {"file": ("speech_only.wav", buf.getvalue(), "audio/wav")}
        else:
            raise TypeError(f"Неподдерживаемый тип аудио: {type(audio)}")

        form_data: Dict[str, Any] = {}
        if "language" in kwargs and kwargs["language"] is not None:
            form_data["language"] = str(kwargs["language"])
        if "beam_size" in kwargs:
            form_data["beam_size"] = int(kwargs["beam_size"])
        if "vad_filter" in kwargs:
            form_data["vad_filter"] = str(kwargs["vad_filter"]).lower()
        if "condition_on_previous_text" in kwargs:
            form_data["condition_on_previous_text"] = str(kwargs["condition_on_previous_text"]).lower()
        if "initial_prompt" in kwargs and kwargs["initial_prompt"]:
            form_data["initial_prompt"] = str(kwargs["initial_prompt"])

        logger.debug("Отправка запроса транскрибации на %s (form_data=%s)", url, form_data)
        post_kwargs: Dict[str, Any] = {}
        if type(client).__name__ != "TestClient":
            post_kwargs["timeout"] = self.timeout

        resp = client.post(url, files=files, data=form_data, **post_kwargs)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Ошибка микросервиса транскрибации ({resp.status_code}): {resp.text}"
            )

        resp_json = resp.json()
        segments = [
            TranscriptionSegment(
                id=seg["id"],
                start=seg["start"],
                end=seg["end"],
                text=seg["text"],
                avg_logprob=seg.get("avg_logprob", 0.0),
                no_speech_prob=seg.get("no_speech_prob", 0.0),
            )
            for seg in resp_json.get("segments", [])
        ]

        result = TranscriptionResult(
            text=resp_json.get("text", ""),
            language=resp_json.get("language", "ru"),
            language_probability=float(resp_json.get("language_probability", 1.0)),
            duration=float(resp_json.get("duration", 0.0)),
            segments=segments,
        )
        logger.debug(
            "Успешная транскрибация через REST API: lang=%s, dur=%.2f, segs=%d",
            result.language,
            result.duration,
            len(result.segments),
        )
        return result

    def close(self) -> None:
        if self._owned_client is not None:
            self._owned_client.close()
            self._owned_client = None

    def __enter__(self) -> "RestTranscriberClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
