"""Streaming CPU speech detection using Faster-Whisper's bundled Silero model."""

import numpy as np
from onnxruntime.capi import onnxruntime_pybind11_state as ort

FRAME_SAMPLES = 512
CONTEXT_SAMPLES = 64


class SileroDetector:
    def __init__(self):
        try:
            from faster_whisper.vad import get_vad_model
            self.session = get_vad_model().session
        except (ImportError, OSError, RuntimeError) as exc:
            raise RuntimeError(f"Could not initialize local Silero VAD: {exc}") from exc
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)

    def probability(self, samples: np.ndarray) -> float:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if len(samples) != FRAME_SAMPLES:
            raise ValueError(f"Silero requires exactly {FRAME_SAMPLES} audio samples.")
        frame = samples.reshape(1, -1)
        input_audio = np.concatenate((self.context, frame), axis=1)
        try:
            output, self.h, self.c = self.session.run(
                None, {"input": input_audio, "h": self.h, "c": self.c}
            )
        except (ort.Fail, ort.InvalidArgument, ort.RuntimeException, RuntimeError) as exc:
            raise RuntimeError(f"Silero VAD inference failed: {exc}") from exc
        self.context = frame[:, -CONTEXT_SAMPLES:].copy()
        return float(output.reshape(-1)[0])
