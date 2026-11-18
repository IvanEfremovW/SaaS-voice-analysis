"""Вывод таймкодов речи и тишины для аудиофайла."""

import argparse
import json
from pathlib import Path
from typing import Literal, TypedDict

import librosa

from .vads import SileroVADAdapter


class TimelineSegment(TypedDict):
    start: float
    end: float
    type: Literal["speech", "silence"]


def build_timeline(
    speech_segments: list[dict[str, float]], duration: float
) -> list[TimelineSegment]:
    """Заполняет паузы между упорядоченными речевыми интервалами."""
    timeline: list[TimelineSegment] = []
    cursor = 0.0

    for segment in speech_segments:
        start = max(cursor, segment["start"])
        end = min(duration, segment["end"])
        if end <= start:
            continue
        if start > cursor:
            timeline.append({"start": cursor, "end": start, "type": "silence"})
        timeline.append({"start": start, "end": end, "type": "speech"})
        cursor = end

    if cursor < duration:
        timeline.append({"start": cursor, "end": duration, "type": "silence"})
    return timeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Путь к аудиофайлу")
    parser.add_argument("--threshold", type=float, default=0.5, help="Порог Silero VAD")
    args = parser.parse_args()

    audio, sample_rate = librosa.load(args.input, sr=16000, mono=True)
    _, speech_segments = SileroVADAdapter(threshold=args.threshold).process(audio, sr=sample_rate)
    duration = len(audio) / sample_rate
    timeline = build_timeline(speech_segments, round(duration, 3) or duration)
    print(json.dumps(timeline))


if __name__ == "__main__":
    main()
