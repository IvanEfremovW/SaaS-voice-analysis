"""Benchmark bookkeeping checks without loading model weights."""

import json
import sys
from pathlib import Path

from stt import TranscriptionResult
from stt.benchmark import main
from stt.benchmark_report import edit_distance, tokens, main as report_main


def test_word_error_normalization() -> None:
    assert tokens("Ёлка, ДА!") == ["елка", "да"]
    assert edit_distance(["да", "сто", "рублей"], ["нет", "рублей", "сегодня"]) == 3
    assert edit_distance([], ["да"]) == 1
    assert edit_distance(["да"], []) == 1


def test_runner_and_report(tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"fake audio")
    output = tmp_path / "results"
    config = tmp_path / "variants.json"
    config.write_text('[{"name":"plain","options":{"vad_filter":false}}]')
    calls = []

    class FakeTranscriber:
        def transcribe(self, path, **options):
            calls.append(options)
            return TranscriptionResult(text="Да", language="ru", language_probability=1,
                                       duration=10, segments=[])

    monkeypatch.setattr("stt.benchmark.get_transcriber", lambda config: FakeTranscriber())
    monkeypatch.setattr(sys, "argv", ["benchmark", "--input", str(audio), "--output", str(output),
                                     "--config", str(config), "--repeats", "2"])
    main()
    assert len(calls) == 3  # One warm-up and two measured calls.
    records = list(output.glob("000_*.json"))
    assert len(records) == 2
    assert json.loads(records[0].read_text())["status"] == "ok"
    references = tmp_path / "references"
    references.mkdir()
    (references / "call.txt").write_text("да")
    monkeypatch.setattr(sys, "argv", ["report", str(output), "--references", str(references)])
    report_main()
    assert "0.000" in (output / "report.md").read_text()
    assert (output / "metrics.csv").is_file()
