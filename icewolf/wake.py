"""Opt-in local phrase recognition and openWakeWord detection."""

from pathlib import Path
import re

import numpy as np

from .audio import SpeechTooLong

WAKE_FRAME_SAMPLES = 1280
FEATURE_DIR = Path(__file__).resolve().parent.parent / "models" / "openwakeword"


def is_icewolf_phrase(text: str) -> bool:
    words = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    return re.fullmatch(r"hey\s+ice\s*wolf", words) is not None


class IcewolfPhraseListener:
    """Experimental local VAD plus Whisper wake phrase recognition."""

    def __init__(self, voice, inline_request_matcher=None, end_silence_seconds=3.0):
        self.voice = voice
        self.inline_request_matcher = inline_request_matcher
        self.end_silence_seconds = end_silence_seconds
        self.inline_request = ""

    def wait(self, stream, stop_event=None) -> bool:
        while stop_event is None or not stop_event.is_set():
            try:
                if self.inline_request_matcher is None:
                    audio = self.voice._record_until_silence(
                        3, 0.01, "silero", 0.5, stream, stop_event, wait_for_speech=True
                    )
                else:
                    audio = self.voice._record_until_silence(
                        30, 0.01, "silero", 0.5, stream, stop_event,
                        wait_for_speech=True, end_silence_seconds=self.end_silence_seconds,
                        fail_on_limit=True,
                    )
            except SpeechTooLong as exc:
                raise RuntimeError("Wake request exceeded 30 seconds; please try again.") from exc
            if audio is None:
                continue
            stream.stop()
            try:
                segments, _ = self.voice.model.transcribe(
                    audio.reshape(-1), beam_size=5, language="en",
                    initial_prompt="Hey Icewolf.", condition_on_previous_text=False,
                )
                text = " ".join(segment.text.strip() for segment in segments)
            except (OSError, ValueError, RuntimeError) as exc:
                raise RuntimeError(f"Wake phrase transcription failed: {exc}") from exc
            if (stop_event is None or not stop_event.is_set()) and is_icewolf_phrase(text):
                return True
            match = re.match(r"^\s*hey[\s,]+ice\s*wolf\b[\s,.:!?]+(.+?)\s*$",
                             text, re.IGNORECASE)
            if (self.inline_request_matcher is not None and match
                    and (stop_event is None or not stop_event.is_set())
                    and self.inline_request_matcher(match.group(1))):
                self.inline_request = match.group(1)
                return True
            if stop_event is None or not stop_event.is_set():
                stream.start()
        return False


class WakeWordListener:
    def __init__(self, model_path: Path, threshold: float = 0.5):
        if not 0 < threshold <= 1:
            raise ValueError("Wake threshold must be greater than 0 and at most 1.")
        model_path = model_path.expanduser().resolve()
        mel = FEATURE_DIR / "melspectrogram.onnx"
        embedding = FEATURE_DIR / "embedding_model.onnx"
        missing = [p for p in (model_path, mel, embedding) if not p.is_file()]
        if missing:
            raise ValueError("Missing wake-word model files: " + ", ".join(map(str, missing)))
        if model_path.suffix.lower() != ".onnx":
            raise ValueError("Wake-word model must be an openWakeWord .onnx file.")
        try:
            from openwakeword.model import Model
            from onnxruntime.capi import onnxruntime_pybind11_state as ort
        except ImportError as exc:
            raise RuntimeError(
                "Wake-word dependencies are missing; install requirements-wake.txt."
            ) from exc
        self._errors = (OSError, ValueError, RuntimeError, ort.Fail, ort.InvalidArgument,
                        ort.NoSuchFile, ort.InvalidGraph, ort.InvalidProtobuf,
                        ort.RuntimeException, ort.NotImplemented)
        try:
            self.model = Model(
                wakeword_models=[str(model_path)], inference_framework="onnx",
                melspec_model_path=str(mel), embedding_model_path=str(embedding),
            )
        except self._errors as exc:
            raise RuntimeError(f"Could not load wake-word model: {exc}") from exc
        if len(self.model.models) != 1:
            raise RuntimeError("Wake-word model must contain exactly one wake phrase.")
        self.model_key = next(iter(self.model.models))
        if self.model.model_outputs[self.model_key] != 1:
            raise RuntimeError("Wake-word model must have a single binary output.")
        self.threshold = threshold

    def wait(self, stream, stop_event=None) -> bool:
        self.model.reset()
        while stop_event is None or not stop_event.is_set():
            samples, overflowed = stream.read(WAKE_FRAME_SAMPLES)
            if overflowed:
                raise RuntimeError("Microphone input overflowed while listening for the wake word.")
            if len(samples) != WAKE_FRAME_SAMPLES:
                raise RuntimeError("Microphone returned an incomplete wake-word audio frame.")
            pcm = (np.clip(samples.reshape(-1), -1.0, 1.0) * 32767).astype(np.int16)
            try:
                predictions = self.model.predict(pcm)
            except self._errors as exc:
                raise RuntimeError(f"Wake-word detection failed: {exc}") from exc
            if self.model_key not in predictions:
                raise RuntimeError("Wake-word model returned an unexpected prediction.")
            if float(predictions[self.model_key]) >= self.threshold:
                return True
        return False
