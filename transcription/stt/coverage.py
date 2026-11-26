"""Поиск участков голосовой активности без распознанных слов."""

from collections.abc import Iterable, Iterator

from .interfaces import TranscriptionSegment


MIN_SPEECH_GAP = 3.0
RETRY_CONTEXT = 4.0
MAX_RETRY_CORE = 22.0
MAX_RETRIES = 20


def uncovered_intervals(
    segments: list[TranscriptionSegment], duration: float
) -> Iterator[tuple[float, float]]:
    spans = sorted(
        (part.start, part.end)
        for segment in segments
        for part in (segment.words or [segment])
        if part.text.strip()
    )
    covered_until = 0.0
    for start, end in spans:
        if start - covered_until >= MIN_SPEECH_GAP:
            yield covered_until, start
        covered_until = max(covered_until, end)
    if duration - covered_until >= MIN_SPEECH_GAP:
        yield covered_until, duration


def retry_intervals(
    gaps: Iterable[tuple[float, float]], speech: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    candidates: list[tuple[float, float]] = []
    speech_index = 0
    for gap_start, gap_end in gaps:
        while speech_index < len(speech) and speech[speech_index][1] <= gap_start:
            speech_index += 1
        index = speech_index
        while index < len(speech) and speech[index][0] < gap_end:
            start = max(gap_start, speech[index][0])
            end = min(gap_end, speech[index][1])
            if end - start >= MIN_SPEECH_GAP:
                while start + MAX_RETRY_CORE < end:
                    candidates.append((start, start + MAX_RETRY_CORE))
                    start += MAX_RETRY_CORE
                candidates.append((start, end))
            index += 1
    return sorted(candidates, key=lambda interval: interval[0] - interval[1])[:MAX_RETRIES]
