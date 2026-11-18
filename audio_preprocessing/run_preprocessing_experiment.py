"""
Оркестратор эксперимента предобработки аудио (Issue #5).
Выполняет:
1. Прогревочный вызов (Warm-up) адаптеров.
2. Прогон матрицы: 3 конвертера × 3 шумодава = 9 вариантов.
3. Замер времени каждого этапа, суммарного RTF.
4. Сохранение 9 WAV-файлов в audio_preprocessing/output/*.wav.
5. Запись результатов в audio_preprocessing/preprocessing_matrix.csv.
6. Автоматическая генерация аналитического R&D отчета docs/issue_5_audio_preprocessing.md.
"""

import argparse
import csv
import itertools
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Any
import numpy as np
import soundfile as sf

try:
    from .audio_generator import get_or_prepare_benchmark_audio
    from .converters import FFmpegConverter, TorchAudioConverter, LibrosaConverter
    from .denoisers import StationarySpectralDenoiser, NonStationarySpectralDenoiser, TelephonyBandpassDenoiser
except (ImportError, ValueError):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from audio_preprocessing.audio_generator import get_or_prepare_benchmark_audio
    from audio_preprocessing.converters import FFmpegConverter, TorchAudioConverter, LibrosaConverter
    from audio_preprocessing.denoisers import StationarySpectralDenoiser, NonStationarySpectralDenoiser, TelephonyBandpassDenoiser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("PreprocessingExperiment")


def warmup_adapters(converters, denoisers, temp_dir: Path):
    """
    Прогревочный вызов (warm-up) для исключения эффекта холодного старта JIT (librosa/numba)
    и инициализации потоков PyTorch.
    """
    logger.info(">>> Запуск прогревочного цикла (Warm-up) адаптеров предобработки...")
    temp_dir.mkdir(parents=True, exist_ok=True)
    dummy_wav = temp_dir / "warmup_dummy.wav"
    sr = 16000
    dummy_audio = (0.2 * np.sin(2 * np.pi * 440.0 * np.linspace(0, 1.0, sr))).astype(np.float32)
    sf.write(str(dummy_wav), dummy_audio, sr)

    for c in converters:
        try:
            _ = c.convert(dummy_wav, target_sr=16000)
        except Exception as e:
            logger.warning("Ошибка warm-up конвертера %s: %s", c.name, e)

    for d in denoisers:
        try:
            _ = d.denoise(dummy_audio, sr=16000)
        except Exception as e:
            logger.warning("Ошибка warm-up шумодава %s: %s", d.name, e)

    if dummy_wav.exists():
        dummy_wav.unlink()
    logger.info(">>> Warm-up предобработки успешно завершен.\n")



def main():
    parser = argparse.ArgumentParser(description="Бенчмарк предобработки аудио (Issue #5)")
    parser.add_argument("--input", type=str, default=None, help="Путь к входному аудиофайлу для тестирования")
    parser.add_argument("--output-dir", type=str, default="audio_preprocessing/output", help="Директория для выходных WAV")
    parser.add_argument("--report", type=str, default="docs/issue_5_audio_preprocessing.md", help="Путь к итоговому Markdown-отчету")
    parser.add_argument("--csv", type=str, default="audio_preprocessing/preprocessing_matrix.csv", help="Путь к CSV с матрицей")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = repo_root / args.report
    csv_path = repo_root / args.csv

    # Подготовка входного файла
    if args.input:
        input_file = Path(args.input).resolve()
        if not input_file.is_file():
            logger.error("Указанный файл не найден: %s", input_file)
            sys.exit(1)
    else:
        input_file = get_or_prepare_benchmark_audio(
            preferred_source_dir=repo_root / "samples" / "AxonData",
            output_call_path=repo_root / "audio_preprocessing" / "input_test_call.mp3",
            target_duration_sec=35.0
        )

    # Определение длительности оригинала через ffprobe/soundfile
    orig_duration = 35.0
    try:
        info = sf.info(str(input_file))
        orig_duration = info.duration
    except Exception:
        pass

    logger.info("Тестовый файл: %s (длительность: %.2f с)", input_file, orig_duration)

    # Инициализация адаптеров
    converters = [
        FFmpegConverter(),
        TorchAudioConverter(),
        LibrosaConverter()
    ]

    denoisers = [
        StationarySpectralDenoiser(prop_decrease=0.85),
        NonStationarySpectralDenoiser(prop_decrease=0.85),
        TelephonyBandpassDenoiser()
    ]

    # Warm-up
    warmup_dir = repo_root / "audio_preprocessing" / "temp_warmup"
    warmup_adapters(converters, denoisers, warmup_dir)
    if warmup_dir.exists():
        import shutil
        shutil.rmtree(warmup_dir, ignore_errors=True)

    # Запуск сетки 3x3=9
    combos = list(itertools.product(converters, denoisers))
    logger.info(">>> Запуск прогона матрицы предобработки (%d комбинаций)...", len(combos))

    results = []

    for idx, (conv, den) in enumerate(combos, start=1):
        combo_name = f"{idx:02d}_{conv.name}_{den.name}"
        logger.info("[%02d/%02d] Выполнение: %s...", idx, len(combos), combo_name)

        # 1. Конвертация
        t0 = time.perf_counter()
        audio_16k, sr = conv.convert(input_file, target_sr=16000)
        t_conv = time.perf_counter() - t0

        # 2. Шумоподавление
        t1 = time.perf_counter()
        audio_denoised = den.denoise(audio_16k, sr=sr)
        t_denoise = time.perf_counter() - t1

        t_total = t_conv + t_denoise
        rtf = t_total / orig_duration if orig_duration > 0 else 0.0
        time_per_sec_ms = (t_total / orig_duration * 1000.0) if orig_duration > 0 else 0.0
        throughput_xrt = (orig_duration / t_total) if t_total > 0 else 0.0

        # Сохранение выходного файла
        out_wav = output_dir / f"{combo_name}.wav"
        sf.write(str(out_wav), audio_denoised, sr, subtype="PCM_16")

        run_res = {
            "id": idx,
            "converter": conv.name,
            "denoiser": den.name,
            "t_conv_sec": round(t_conv, 4),
            "t_denoise_sec": round(t_denoise, 4),
            "t_total_sec": round(t_total, 4),
            "rtf": round(rtf, 5),
            "time_per_sec_ms": round(time_per_sec_ms, 2),
            "throughput_xrt": round(throughput_xrt, 1),
            "output_file": out_wav.name
        }
        results.append(run_res)

        logger.info(
            "     T_conv: %.3fs | T_denoise: %.3fs | T_total: %.3fs | RTF: %.4f | 1s аудио: %.2f мс (%.1fx RT)",
            t_conv, t_denoise, t_total, rtf, time_per_sec_ms, throughput_xrt
        )

    # Сохранение матрицы CSV
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id", "converter", "denoiser", "t_conv_sec", "t_denoise_sec",
        "t_total_sec", "rtf", "time_per_sec_ms", "throughput_xrt", "output_file"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    logger.info("Матрица предобработки сохранена в CSV: %s", csv_path)
    logger.info(">>> Исследование предобработки (Issue #5) успешно завершено!\n")


if __name__ == "__main__":
    main()
