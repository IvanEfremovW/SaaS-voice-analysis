"""Sequential local benchmark; does not change service configuration."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, Field, TypeAdapter

from stt import TranscriberConfig, get_transcriber

logger = logging.getLogger(__name__)


class Variant(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    options: dict[str, object]


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("samples/zakazchik"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("benchmark_variants.json"))
    parser.add_argument("--variants", nargs="+")
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.repeats < 1 or (args.limit is not None and args.limit < 1):
        parser.error("repeats and limit must be positive")
    variants = TypeAdapter(list[Variant]).validate_json(args.config.read_text(encoding="utf-8"))
    if len({v.name for v in variants}) != len(variants):
        parser.error("Variant names must be unique")
    if args.variants:
        unknown = set(args.variants) - {v.name for v in variants}
        if unknown:
            parser.error(f"Unknown variants: {sorted(unknown)}")
        variants = [v for v in variants if v.name in args.variants]
    files = ([args.input] if args.input.is_file() else sorted(
        p for p in args.input.rglob("*") if p.suffix.lower() in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
    ))
    files = files[:args.limit]
    if not files or not variants:
        parser.error("No input files or variants")
    # Never mix incompatible runs or overwrite previously measured results.
    args.output.mkdir(parents=True, exist_ok=False)
    config = TranscriberConfig(model_size=args.model, device=args.device,
        compute_type=args.compute_type, language="ru", word_timestamps=True,
        recover_missing_speech=False, condition_on_previous_text=False)
    versions: dict[str, str] = {}
    for package in ("faster-whisper", "ctranslate2", "onnxruntime", "numpy", "av"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed"
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "versions": versions, "config": config.model_dump(),
        "variants": [v.model_dump() for v in variants], "seed": args.seed,
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "git_status": subprocess.run(["git", "status", "--short"], capture_output=True, text=True).stdout,
        "files": [{"id": f"{i:03d}", "path": str(p.resolve()), "sha256": file_hash(p)} for i, p in enumerate(files)],
    }
    write_json(args.output / "manifest.json", manifest)
    started = perf_counter()
    transcriber = get_transcriber(config=config)
    manifest["model_load_s"] = perf_counter() - started
    manifest["actual_device"] = getattr(transcriber, "actual_device", args.device)
    manifest["actual_compute_type"] = getattr(transcriber, "actual_compute_type", args.compute_type)
    # Full first call warms the model, VAD and recovery paths; excluded from timings.
    logger.info("Warm-up on %s (excluded from measurements)", files[0].name)
    started = perf_counter()
    transcriber.transcribe(files[0], vad_filter=True, recover_missing_speech=True)
    manifest["warmup_s"] = perf_counter() - started
    write_json(args.output / "manifest.json", manifest)
    jobs = [(i, p, v, repeat) for repeat in range(args.repeats)
            for i, p in enumerate(files) for v in variants]
    random.Random(args.seed).shuffle(jobs)
    failures = 0
    for number, (file_id, path, variant, repeat) in enumerate(jobs, 1):
        logger.info("[%d/%d] %s / %s / repeat %d", number, len(jobs), path.name, variant.name, repeat + 1)
        record: dict[str, object] = {"file_id": f"{file_id:03d}", "file": str(path.resolve()),
            "variant": variant.name, "repeat": repeat + 1, "options": variant.options}
        started = perf_counter()
        try:
            result = transcriber.transcribe(path, **variant.options)
            elapsed = perf_counter() - started
            record.update(status="ok", elapsed_s=elapsed, duration_s=result.duration,
                rtf=elapsed / result.duration if result.duration else None, result=result.model_dump())
        except Exception as exc:
            failures += 1
            logger.exception("Failed job")
            record.update(status="error", elapsed_s=perf_counter() - started, error=str(exc))
        write_json(args.output / f"{file_id:03d}_{variant.name}_{repeat + 1}.json", record)
    logger.info("Finished: %s; failures=%d", args.output, failures)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
