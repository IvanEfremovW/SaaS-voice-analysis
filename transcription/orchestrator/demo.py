"""
Демонстрационный скрипт работы внешнего оркестратора звонков (CallProcessingPipeline).
Наглядно показывает заказчику и техлиду работу модулей как изолированных «чёрных ящиков»:
Режим 1: Loader -> Preprocessor (Converter + Denoiser + VAD) -> Transcriber (Whisper) -> Remap
Режим 2: Loader -> Transcriber (напрямую на сыром аудио без предобработки)
"""

import argparse
import logging
from pathlib import Path
import sys
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Orchestrator.Demo")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from audio_preprocessing import get_audio_pipeline
from orchestrator import (
    CallProcessingPipeline,
    LocalMockAudioLoader,
)
from stt import TranscriberConfig, get_transcriber
from stt.config import DEFAULT_MODEL_SIZE


def run_demo(audio_path: Path, model_size: str = DEFAULT_MODEL_SIZE) -> None:
    print("\n" + "=" * 80)
    print("  ДЕМОНСТРАЦИЯ ОРКЕСТРАТОРА ОБРАБОТКИ ЗВОНКОВ (MOCK-PIPELINE)")
    print("  Архитектура: Полная изоляция модулей («Чёрные ящики»)")
    print("=" * 80)
    print(f"Целевой аудиофайл: {audio_path}")
    print(f"Используемая модель Whisper: {model_size}\n")

    # 1. Инициализация общих компонентов
    loader = LocalMockAudioLoader(base_dir=REPO_ROOT)
    stt_config = TranscriberConfig(model_size=model_size, device="cpu", compute_type="int8")
    transcriber = get_transcriber(config=stt_config)
    preprocessor = get_audio_pipeline()

    # --- РЕЖИМ 1: С ВКЛЮЧЕННОЙ ПРЕДОБРАБОТКОЙ ---
    print("\n" + "-" * 80)
    print("▶ РЕЖИМ 1: Включена предобработка (Loader -> Preprocessor -> STT -> Remapper)")
    print("-" * 80)

    pipeline_with_prep = CallProcessingPipeline(
        audio_loader=loader,
        preprocessor=preprocessor,
        transcriber=transcriber,
        remap_timestamps=True,
    )

    t0 = time.perf_counter()
    result_with_prep = pipeline_with_prep.run(audio_path, language="ru")
    duration_with_prep = time.perf_counter() - t0

    print(f"✓ Обработка завершена за: {duration_with_prep:.2f} сек")
    print(f"✓ Язык: {result_with_prep.language} (p={result_with_prep.language_probability:.2f})")
    print(f"✓ Итоговая длительность на шкале звонка: {result_with_prep.duration:.2f} сек")
    print(f"✓ Количество сегментов речи: {len(result_with_prep.segments)}")
    print(f"✓ Полный текст: \"{result_with_prep.text.strip()}\"\n")
    print("Сегменты с восстановленными таймкодами звонка:")
    for seg in result_with_prep.segments[:5]:
        print(f"   [{seg.start:6.2f}s -> {seg.end:6.2f}s] {seg.text}")
    if len(result_with_prep.segments) > 5:
        print(f"   ... и еще {len(result_with_prep.segments) - 5} сегментов")

    # --- РЕЖИМ 2: БЕЗ ПРЕДОБРАБОТКИ ---
    print("\n" + "-" * 80)
    print("▶ РЕЖИМ 2: Предобработка выключена (Loader -> STT напрямую на сыром аудио)")
    print("-" * 80)

    pipeline_direct = CallProcessingPipeline(
        audio_loader=loader,
        preprocessor=None,  # Предобработка отключена
        transcriber=transcriber,
        remap_timestamps=False,
    )

    t1 = time.perf_counter()
    result_direct = pipeline_direct.run(audio_path, language="ru")
    duration_direct = time.perf_counter() - t1

    print(f"✓ Обработка завершена за: {duration_direct:.2f} сек")
    print(f"✓ Язык: {result_direct.language} (p={result_direct.language_probability:.2f})")
    print(f"✓ Длительность сырого аудио: {result_direct.duration:.2f} сек")
    print(f"✓ Количество сегментов: {len(result_direct.segments)}")
    print(f"✓ Полный текст: \"{result_direct.text.strip()}\"\n")
    print("Сегменты сырого аудио:")
    for seg in result_direct.segments[:5]:
        print(f"   [{seg.start:6.2f}s -> {seg.end:6.2f}s] {seg.text}")
    if len(result_direct.segments) > 5:
        print(f"   ... и еще {len(result_direct.segments) - 5} сегментов")

    print("\n" + "=" * 80)
    print("  ИТОГИ ДЕМОНСТРАЦИИ:")
    print(f"  • Время работы с VAD:     {duration_with_prep:.2f} сек")
    print(f"  • Время работы напрямую:  {duration_direct:.2f} сек")
    print("  • Изоляция модулей:       ПОЛНАЯ (отсутствуют перекрестные импорты)")
    print("  • Транскрибатор:          НЕ знает, было ли аудио предобработано")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Демонстрация оркестратора звонков")
    parser.add_argument(
        "--file",
        type=Path,
        default=REPO_ROOT / "audio_preprocessing" / "input_test_call.mp3",
        help="Путь к аудиофайлу звонка",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL_SIZE,
        help="Размер модели Whisper (по умолчанию: %(default)s)",
    )
    args = parser.parse_args()

    if not args.file.is_file():
        logger.error("Файл не найден: %s", args.file)
        sys.exit(1)

    run_demo(args.file, model_size=args.model)
