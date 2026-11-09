"""Границы доступа и размера запросов для HTTP-сервисов аудио."""

import os
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Protocol

from fastapi import Header, HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class AudioUploadLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.active_uploads = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        if self.active_uploads >= 2:
            await JSONResponse({"detail": "Сервис занят"}, status_code=503)(scope, receive, send)
            return

        size = 0

        async def limited_receive() -> Message:
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Превышен лимит размера запроса")
            return message

        self.active_uploads += 1
        try:
            await self.app(scope, limited_receive, send)
        finally:
            self.active_uploads -= 1


def require_shared_access(
    authorization: Annotated[str | None, Header()] = None
) -> None:
    token = os.getenv("AUDIO_SHARED_TOKEN")
    if not token or not os.getenv("AUDIO_SHARED_ROOT"):
        raise HTTPException(403, "Доступ по пути отключён")
    expected = f"Bearer {token}".encode()
    if not compare_digest((authorization or "").encode(), expected):
        raise HTTPException(401, "Требуется токен доступа", headers={"WWW-Authenticate": "Bearer"})


def shared_path(value: str, extensions: set[str], *, output: bool = False) -> Path:
    root = Path(os.environ["AUDIO_SHARED_ROOT"]).resolve()
    requested = root / value
    try:
        path = requested.resolve()
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(400, "Некорректный путь") from None
    if not path.is_relative_to(root) or path.suffix.lower() not in extensions:
        raise HTTPException(403, "Путь вне разрешённого хранилища или формат запрещён")
    if output and requested.is_symlink():
        raise HTTPException(403, "Символические ссылки для записи запрещены")
    if not output:
        if not path.is_file():
            raise HTTPException(404, "Исходный аудиофайл не найден")
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Превышен лимит размера аудиофайла")
    return path


class AudioInputValidator(Protocol):
    def validate(self, path: Path) -> None:
        """Проверить допустимость декодированного потока до обработки."""
        ...


class PyAVInputValidator(AudioInputValidator):
    """Проверяет фактический объём потока до передачи в декодер модели."""

    def __init__(self, max_seconds: float = 1800, max_samples: int = 64_000_000) -> None:
        self.max_seconds = max_seconds
        self.max_samples = max_samples

    def validate(self, path: Path) -> None:
        import av

        seconds = 0.0
        samples = 0
        try:
            with av.open(str(path), options={"protocol_whitelist": "file,pipe,crypto,data"}) as container:
                if not container.streams.audio:
                    raise HTTPException(400, "Файл не содержит аудиопотока")
                for frame in container.decode(audio=0):
                    channels = len(frame.layout.channels)
                    if not 0 < frame.sample_rate <= 192000 or not 0 < channels <= 8:
                        raise HTTPException(400, "Неподдерживаемые параметры аудиопотока")
                    seconds += frame.samples / frame.sample_rate
                    samples += frame.samples * channels
                    if seconds > self.max_seconds or samples > self.max_samples:
                        raise HTTPException(413, "Превышен лимит декодированного аудио")
        except (av.error.FFmpegError, OSError, ValueError):
            raise HTTPException(400, "Не удалось декодировать аудиофайл") from None
