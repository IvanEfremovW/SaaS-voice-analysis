"""Адаптер T-one для сравнения расшифровок в демо."""

from io import BytesIO
from itertools import groupby
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
from faster_whisper.audio import decode_audio
from huggingface_hub import hf_hub_download
from tone import GreedyCTCDecoder, StreamingCTCModel, StreamingCTCPipeline, StreamingLogprobSplitter
from tone.decoder import LABELS

from .interfaces import BaseTranscriber, TranscriptionResult, TranscriptionSegment, TranscriptionWord


class WordTimingDecoder(GreedyCTCDecoder):
    """Сохраняет границы слов в кадрах CTC при жадном декодировании."""

    def __init__(self) -> None:
        self.phrases: list[list[tuple[str, int, int]]] = []

    def forward(self, logprobs: np.ndarray) -> str:
        words: list[tuple[str, int, int]] = []
        letters: list[str] = []
        start = end = offset = 0
        for token, frames in groupby(logprobs.argmax(axis=1).tolist()):
            frame = offset
            offset += sum(1 for _ in frames)
            if token >= len(LABELS):
                continue
            symbol = LABELS[token]
            if symbol == " ":
                if letters:
                    words.append(("".join(letters), start, end))
                    letters.clear()
                continue
            if not letters:
                start = frame
            letters.append(symbol)
            end = offset
        if letters:
            words.append(("".join(letters), start, end))
        self.phrases.append(words)
        return " ".join(word for word, _, _ in words)


class ToneTranscriber(BaseTranscriber):
    def __init__(self, model_path: Path | None = None) -> None:
        path = model_path or Path(hf_hub_download(
            "t-tech/T-one", "model.onnx", revision="106f3b0b32a9e107eb613312e4ebc61ff3d53926"
        ))
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self._model = StreamingCTCModel(ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        ))

    @property
    def name(self) -> str:
        return "t-one"

    def transcribe(self, audio: str | Path | np.ndarray, **kwargs: object) -> TranscriptionResult:
        sample_rate = self._model.SAMPLE_RATE
        if isinstance(audio, np.ndarray):
            with BytesIO() as buffer:
                sf.write(buffer, audio, 16000, format="WAV", subtype="FLOAT")
                buffer.seek(0)
                samples = decode_audio(buffer, sampling_rate=sample_rate)
        else:
            samples = decode_audio(str(audio), sampling_rate=sample_rate)
        duration = len(samples) / sample_rate

        decoder = WordTimingDecoder()
        pipeline = StreamingCTCPipeline(self._model, StreamingLogprobSplitter(), decoder)
        phrases = pipeline.forward_offline(np.rint(samples * 32768).astype(np.int32))
        segments: list[TranscriptionSegment] = []
        for phrase, frames in zip(phrases, decoder.phrases, strict=True):
            if not frames:
                continue
            start = min(phrase.start_time, duration)
            end = min(phrase.end_time, duration)
            words = [
                TranscriptionWord(
                    text=word,
                    start=min(end, round(start + left * self._model.FRAME_SIZE, 3)),
                    end=min(end, round(start + right * self._model.FRAME_SIZE, 3)),
                    probability=0.0,
                )
                for word, left, right in frames
            ]
            segments.append(TranscriptionSegment(
                id=len(segments), start=start, end=end, text=phrase.text,
                avg_logprob=0.0, no_speech_prob=0.0, words=words,
            ))
        return TranscriptionResult(
            text=" ".join(segment.text for segment in segments), language="ru",
            language_probability=0.0, duration=duration, segments=segments,
        )
