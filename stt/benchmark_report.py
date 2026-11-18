"""Summarize a benchmark; optionally score full manual transcripts by WER."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold().replace("ё", "е"))


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, expected in enumerate(reference, 1):
        current = [i]
        for j, actual in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (expected != actual)))
        previous = current
    return previous[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--references", type=Path, help="Directory containing <audio stem>.txt, full manual transcripts")
    args = parser.parse_args()
    rows: list[dict[str, object]] = []
    groups: dict[str, list[float]] = defaultdict(list)
    lines = ["# Результаты Whisper", "", "Время включает чтение аудио, VAD и включённое восстановление; загрузка и прогрев исключены.", "",
             "| Файл | Вариант | Повтор | Секунды | RTF | Слов | WER |", "|---|---|---:|---:|---:|---:|---:|"]
    for path in sorted(args.directory.glob("*.json")):
        if path.name == "manifest.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["status"] != "ok":
            lines.append(f"\nОшибка {path.name}: {record['error']}\n")
            continue
        stem = Path(record["file"]).stem
        result = record["result"]
        words = tokens(result["text"])
        wer = None
        reference = args.references / f"{stem}.txt" if args.references else None
        if reference and reference.is_file():
            expected = tokens(reference.read_text(encoding="utf-8"))
            if expected:
                wer = edit_distance(expected, words) / len(expected)
        row = {key: record[key] for key in ("file", "variant", "repeat", "elapsed_s", "duration_s", "rtf")}
        row.update(words=len(words), wer=wer)
        rows.append(row)
        groups[record["variant"]].append(record["rtf"])
        wer_text = f"{wer:.3f}" if wer is not None else "—"
        lines.append(f"| {stem[:8]} | {record['variant']} | {record['repeat']} | {record['elapsed_s']:.1f} | {record['rtf']:.3f} | {len(words)} | {wer_text} |")
        transcript = [f"{s['start']:.2f}–{s['end']:.2f}  {s['text']}" for s in result["utterances"]]
        path.with_suffix(".txt").write_text("\n".join(transcript), encoding="utf-8")
    lines.extend(["", "Медиана RTF по успешным измерениям (сравнивать только одинаковые наборы файлов):", ""])
    lines.extend(f"- {name}: {statistics.median(values):.3f}, n={len(values)}" for name, values in sorted(groups.items()))
    lines.extend(["", "Количество слов не является оценкой качества. WER требует ручного эталона полного звонка; числа словами и цифрами автоматически не приравниваются."])
    (args.directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if rows:
        with (args.directory / "metrics.csv").open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(args.directory / "report.md")


if __name__ == "__main__":
    main()
