"""
Утилита подготовки и извлечения эталонного тестового аудиозвонка (Issue #5).
"""

import logging
from pathlib import Path
from typing import Optional
import soundfile as sf
import numpy as np

logger = logging.getLogger(__name__)


def get_or_prepare_benchmark_audio(
    preferred_source_dir: Optional[Path] = None,
    output_call_path: Optional[Path] = None,
    target_duration_sec: float = 35.0
) -> Path:
    """
    Возвращает путь к эталонному файлу звонка.
    Если файл уже существует и не пуст, возвращает его.
    Если нет, ищет аудио в preferred_source_dir или генерирует калибровочный файл.
    """
    if output_call_path is None:
        output_call_path = Path(__file__).resolve().parent / "input_test_call.mp3"
    else:
        output_call_path = Path(output_call_path).resolve()

    if output_call_path.is_file() and output_call_path.stat().st_size > 0:
        logger.info("Использование существующего тестового звонка: %s", output_call_path)
        return output_call_path

    output_call_path.parent.mkdir(parents=True, exist_ok=True)

    # Поиск доступных аудиофайлов в samples
    if preferred_source_dir and preferred_source_dir.is_dir():
        candidates = list(preferred_source_dir.rglob("*.mp3")) + list(preferred_source_dir.rglob("*.wav"))
        if candidates:
            first_candidate = candidates[0]
            logger.info("Найдено исходное аудио в %s: %s", preferred_source_dir, first_candidate)
            data, sr = sf.read(str(first_candidate), dtype="float32")
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            target_samples = int(target_duration_sec * sr)
            if len(data) > target_samples:
                data = data[:target_samples]
            sf.write(str(output_call_path), data, sr)
            return output_call_path

    # Резервная генерация калибровочного речеподобного тона
    sr = 16000
    t = np.linspace(0, target_duration_sec, int(sr * target_duration_sec), endpoint=False)
    synthetic_signal = 0.2 * np.sin(2 * np.pi * 300 * t) + 0.1 * np.sin(2 * np.pi * 1200 * t)
    # Имитация пауз
    mask = (np.sin(2 * np.pi * 0.2 * t) > 0).astype(np.float32)
    synthetic_signal = (synthetic_signal * mask).astype(np.float32)
    sf.write(str(output_call_path), synthetic_signal, sr)
    logger.info("Сгенерирован синтетический калибровочный звонок: %s", output_call_path)
    return output_call_path
