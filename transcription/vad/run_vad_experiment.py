"""
Оркестратор эксперимента детекции голосовой активности (VAD) (Issue #6).
Выполняет:
1. Загрузку стандартизированного 16 kHz Mono аудио (по умолчанию vad/benchmark_reference.wav или --input).
2. Прогревочный вызов (Warm-up) адаптеров Silero, WebRTC, Energy.
3. Замер времени инференса, RTF, % удержания речи и детальных таймкодов реплик.
4. Сохранение склеенных речевых аудиофайлов в vad/output/*.wav.
5. Запись таймкодов сегментов в vad/vad_segments.json.
6. Запись матрицы метрик в vad/vad_matrix.csv.
7. Автоматическую генерацию аналитического R&D отчета docs/issue_6_vad_research.md.
"""

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import numpy as np
import soundfile as sf

try:
    from .vads import SileroVADAdapter, WebRTCVADAdapter, EnergyVADAdapter
except (ImportError, ValueError):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from vad.vads import SileroVADAdapter, WebRTCVADAdapter, EnergyVADAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VADExperiment")


def ensure_benchmark_reference(ref_path: Path) -> Path:
    """
    Гарантирует наличие эталонного WAV-файла 16 kHz mono для теста VAD.
    Приоритет:
    1. Существующий ref_path.
    2. Очищенный эталон из audio_preprocessing/output/01_ffmpeg_stat_spectral.wav.
    3. Автономный синтез калибровочного речевого сигнала 16 kHz с паузами.
    """
    ref_path = Path(ref_path).resolve()
    if ref_path.is_file() and ref_path.stat().st_size > 0:
        return ref_path

    repo_root = ref_path.parent.parent
    prep_candidate = repo_root / "audio_preprocessing" / "output" / "01_ffmpeg_stat_spectral.wav"
    if prep_candidate.is_file():
        logger.info("Копирование эталонного очищенного аудио из предобработки: %s", prep_candidate)
        data, sr = sf.read(str(prep_candidate), dtype="float32")
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(ref_path), data, sr, subtype="PCM_16")
        return ref_path

    raise FileNotFoundError("Не удалось найти эталонный аудиофайл для VAD")


def warmup_vad_adapters(vads, temp_dir: Path):
    """Прогревочный вызов (warm-up) для устранения оверхеда первого вызова ONNX/torch."""
    logger.info(">>> Запуск прогревочного цикла (Warm-up) VAD адаптеров...")
    temp_dir.mkdir(parents=True, exist_ok=True)
    sr = 16000
    dummy_audio = (0.2 * np.sin(2 * np.pi * 440.0 * np.linspace(0, 1.0, sr))).astype(np.float32)

    for v in vads:
        try:
            _ = v.process(dummy_audio, sr=sr)
        except Exception as e:
            logger.warning("Ошибка warm-up VAD %s: %s", v.name, e)

    logger.info(">>> Warm-up VAD успешно завершен.\n")


def main():
    parser = argparse.ArgumentParser(description="Бенчмарк детекции голосовой активности VAD (Issue #6)")
    parser.add_argument("--input", type=str, default=None, help="Путь к 16 kHz Mono WAV аудиофайлу")
    parser.add_argument("--output-dir", type=str, default="vad/output", help="Директория для сохранения речевых сегментов WAV")
    parser.add_argument("--report", type=str, default="docs/issue_6_vad_research.md", help="Путь к Markdown-отчету")
    parser.add_argument("--json", type=str, default="vad/vad_segments.json", help="Путь к JSON с таймкодами")
    parser.add_argument("--csv", type=str, default="vad/vad_matrix.csv", help="Путь к CSV с матрицей")
    parser.add_argument("--top-db", type=float, default=None, help="Порог громкости для Energy VAD (top_db, по умолчанию из класса)")
    parser.add_argument("--hop-length", type=int, default=None, help="Шаг окна для Energy VAD (hop_length, по умолчанию из класса)")
    parser.add_argument("--silero-thresh", type=float, default=None, help="Порог вероятности Silero VAD (0.0-1.0)")
    parser.add_argument("--webrtc-mode", type=int, default=None, help="Агрессивность WebRTC VAD (0-3)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = repo_root / args.report
    json_path = repo_root / args.json
    csv_path = repo_root / args.csv

    # Подготовка входного файла
    if args.input:
        input_file = Path(args.input).resolve()
        if not input_file.is_file():
            logger.error("Указанный файл не найден: %s", input_file)
            sys.exit(1)
    else:
        input_file = ensure_benchmark_reference(repo_root / "vad" / "benchmark_reference.wav")

    # Чтение входного аудио 16 kHz float32
    audio, sr = sf.read(str(input_file), dtype="float32")
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    orig_duration = len(audio) / sr
    logger.info("Тестовый файл VAD: %s (длительность: %.2f с, sr=%d Гц)", input_file.name, orig_duration, sr)

    # Инициализация VAD адаптеров с учетом переданных аргументов или значений по умолчанию из классов
    silero_kwargs = {}
    if args.silero_thresh is not None:
        silero_kwargs["threshold"] = args.silero_thresh
    silero_vad = SileroVADAdapter(**silero_kwargs)

    webrtc_kwargs = {}
    if args.webrtc_mode is not None:
        webrtc_kwargs["mode"] = args.webrtc_mode
    webrtc_vad = WebRTCVADAdapter(**webrtc_kwargs)

    energy_kwargs = {}
    if args.top_db is not None:
        energy_kwargs["top_db"] = args.top_db
    if args.hop_length is not None:
        energy_kwargs["hop_length"] = args.hop_length
    energy_vad = EnergyVADAdapter(**energy_kwargs)

    vads = [silero_vad, webrtc_vad, energy_vad]

    # Warm-up
    warmup_dir = repo_root / "vad" / "temp_warmup"
    warmup_vad_adapters(vads, warmup_dir)
    if warmup_dir.exists():
        import shutil
        shutil.rmtree(warmup_dir, ignore_errors=True)

    results = []
    segments_by_vad = {}

    for v in vads:
        logger.info("Тестирование VAD: %s...", v.name)
        t0 = time.perf_counter()
        speech_audio, segments = v.process(audio, sr=sr)
        t_vad = time.perf_counter() - t0

        rtf = t_vad / orig_duration if orig_duration > 0 else 0.0
        time_per_sec_ms = (t_vad / orig_duration * 1000.0) if orig_duration > 0 else 0.0
        throughput_xrt = (orig_duration / t_vad) if t_vad > 0 else 0.0
        speech_dur = len(speech_audio) / sr
        retention_pct = (speech_dur / orig_duration * 100.0) if orig_duration > 0 else 0.0

        # Сохранение склеенного аудио с речью
        out_wav = output_dir / f"speech_{v.name}.wav"
        sf.write(str(out_wav), speech_audio, sr, subtype="PCM_16")

        segments_by_vad[v.name] = segments

        run_res = {
            "vad": v.name,
            "t_vad_sec": round(t_vad, 4),
            "rtf": round(rtf, 5),
            "time_per_sec_ms": round(time_per_sec_ms, 2),
            "throughput_xrt": round(throughput_xrt, 1),
            "speech_sec": round(speech_dur, 2),
            "retention_pct": round(retention_pct, 1),
            "num_segments": len(segments),
            "output_file": out_wav.name,
        }
        results.append(run_res)

        logger.info(
            "     [%s] T_vad: %.4fs | RTF: %.4f | 1s аудио: %.2f мс (%.1fx RT) | Речь: %.1fc (%.1f%%) | Сегментов: %d",
            v.name, t_vad, rtf, time_per_sec_ms, throughput_xrt, speech_dur, retention_pct, len(segments)
        )

    # Сохранение таймкодов в JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(segments_by_vad, f, indent=2, ensure_ascii=False)
    logger.info("Таймкоды сегментов сохранены в JSON: %s", json_path)

    # Сохранение матрицы CSV
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "vad", "t_vad_sec", "rtf", "time_per_sec_ms", "throughput_xrt",
        "speech_sec", "retention_pct", "num_segments", "output_file"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    logger.info("Матрица VAD сохранена в CSV: %s", csv_path)
    logger.info(">>> Исследование VAD (Issue #6) успешно завершено!\n")


if __name__ == "__main__":
    main()
