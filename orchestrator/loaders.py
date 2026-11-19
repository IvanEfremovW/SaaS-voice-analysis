"""
Реализации загрузчиков аудиоданных (паттерн Strategy) для оркестратора.
Включает LocalMockAudioLoader для эмуляции извлечения звонков из хранилища или Mock CRM.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple, Union
import numpy as np
from audio_decode import AudioDecoder, PyAVAudioDecoder

from .interfaces import BaseAudioLoader

logger = logging.getLogger("Orchestrator.Loaders")


class LocalMockAudioLoader(BaseAudioLoader):
    """
    Мок-загрузчик аудиозвонков из локальной файловой системы или общего тома.
    Эмулирует получение аудиозаписи звонка по ID из CRM или медиахранилища.
    """

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        target_sr: Optional[int] = 16000,
        decoder: AudioDecoder | None = None,
    ) -> None:
        """
        :param base_dir: Базовая директория поиска аудиофайлов (если передан относительный путь или ID).
        :param target_sr: Целевая частота дискретизации (по умолчанию 16000 Гц для ML-моделей).
        """
        self.base_dir = Path(base_dir).resolve() if base_dir is not None else None
        self.target_sr = target_sr
        self.decoder = decoder or PyAVAudioDecoder()

    def _resolve_path(self, call_id_or_path: Union[str, Path]) -> Path:
        """
        Находит существующий файл по прямому пути, относительно base_dir или по call_id.
        """
        path = Path(call_id_or_path)

        # 1. Прямой путь
        if path.is_file():
            return path.resolve()

        # 2. Относительно base_dir
        if self.base_dir is not None:
            candidate = self.base_dir / path
            if candidate.is_file():
                return candidate.resolve()

            # 3. Поиск с популярными аудио-расширениями
            if not path.suffix:
                for ext in (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm"):
                    candidate_with_ext = self.base_dir / f"{path.name}{ext}"
                    if candidate_with_ext.is_file():
                        return candidate_with_ext.resolve()

        raise FileNotFoundError(
            f"Аудиофайл звонка не найден: '{call_id_or_path}'. "
            f"Проверенные пути: direct='{path}', base_dir='{self.base_dir}'"
        )

    def load(self, call_id_or_path: Union[str, Path]) -> Tuple[np.ndarray, int]:
        """
        Загружает аудиофайл и приводит его к стандартизированному моно float32 массиву.

        :param call_id_or_path: Идентификатор звонка или путь к файлу.
        :return: Кортеж (1D float32 numpy-массив моно-аудио, sample_rate).
        """
        file_path = self._resolve_path(call_id_or_path)
        logger.debug("Загрузка аудиозаписи звонка из %s", file_path)

        return self.decoder.decode(file_path, self.target_sr)
