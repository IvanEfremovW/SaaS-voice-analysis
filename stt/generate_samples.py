"""
Скрипт генерации артефакта качества транскрибации (Issue DoD №2).
Прогоняет 3 тестовых аудиофайла через модель Whisper 'small'
и сохраняет результаты в stt/transcription_samples.json.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from stt import TranscriberConfig, get_transcriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("STT.GenerateSamples")


def get_target_audio_files(repo_root: Path) -> List[Path]:
    """Возвращает 3 целевых аудиофайла из репозитория."""
    candidates = [
        repo_root / "audio_preprocessing" / "input_test_call.mp3",
        repo_root / "samples" / "test_call_youtube.mp3",
        repo_root
        / "samples"
        / "AxonData"
        / "russian-speech-recognition-dataset"
        / "Call center data samples RU"
        / "1756465406.16342 (RU Pharma Sale)"
        / "1756465406.16342.mp3",
    ]

    existing = [p for p in candidates if p.is_file()]
    if len(existing) < 3:
        raise FileNotFoundError(
            f"Не найдены все 3 аудиофайла. Найдено {len(existing)} из {len(candidates)}: {existing}"
        )
    return existing


def generate_samples(output_path: Path | None = None) -> List[Dict[str, Any]]:
    """
    Выполняет транскрибацию 3 файлов через модель 'small' и сохраняет JSON-отчет.
    """
    repo_root = Path(__file__).resolve().parent.parent
    if output_path is None:
        output_path = repo_root / "stt" / "transcription_samples.json"

    audio_files = get_target_audio_files(repo_root)

    logger.info("Инициализация транскрибатора с моделью 'small' и контекстным промптом...")
    config = TranscriberConfig(
        model_size="small",
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=(
            "Запись телефонного разговора колл-центра на русском языке. "
            "Стоматология, клиника, препарат, грибок, Микозан, упаковка, курс, скидка, евро, рублей."
        ),
    )
    transcriber = get_transcriber(config=config)

    results: List[Dict[str, Any]] = []

    for idx, audio_file in enumerate(audio_files, 1):
        rel_path = audio_file.relative_to(repo_root).as_posix()
        logger.info(
            "[%d/%d] Транскрибация файла: %s ...",
            idx,
            len(audio_files),
            rel_path,
        )
        t0 = time.time()
        res = transcriber.transcribe(audio_file)
        elapsed = time.time() - t0

        first_5_segments = [
            seg.model_dump() for seg in res.segments[:5]
        ]

        logger.info(
            "  -> Успешно! Длительность: %.2fs, Время инференса: %.2fs, Язык: %s, Сегментов: %d",
            res.duration,
            elapsed,
            res.language,
            len(res.segments),
        )

        results.append(
            {
                "file": rel_path,
                "duration": res.duration,
                "language": res.language,
                "language_probability": res.language_probability,
                "inference_time_sec": round(elapsed, 2),
                "text": res.text,
                "segments_count": len(res.segments),
                "first_5_segments": first_5_segments,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info("Результаты успешно сохранены в: %s", output_path)
    return results


if __name__ == "__main__":
    generate_samples()
