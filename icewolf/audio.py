"""Push-to-talk recording, offline transcription, and system speech."""

from pathlib import Path
import sys
from contextlib import nullcontext
from collections import deque


SAMPLE_RATE = 16000
SILENCE_RMS = 0.001
FRAME_SAMPLES = 1600
END_SILENCE_SECONDS = 1.2


class SpeechTooLong(Exception):
    """A complete utterance could not be retained within the recording limit."""


class VoicePipeline:
    def __init__(self, model_path: Path, speak: bool = True):
        model_path = model_path.expanduser().resolve()
        required = ("model.bin", "config.json", "tokenizer.json")
        missing = [name for name in required if not (model_path / name).is_file()]
        if missing:
            raise ValueError(
                f"Whisper model directory {model_path} is missing: {', '.join(missing)}. "
                "Provide a complete local faster-whisper model directory."
            )
        try:
            import sounddevice as sd
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Voice dependencies are missing. Install the packages in requirements.txt."
            ) from exc
        self.sd = sd
        self.level_callback = None
        try:
            self.model = WhisperModel(
                str(model_path), device="cpu", compute_type="int8", local_files_only=True
            )
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError(f"Could not load the local Whisper model: {exc}") from exc
        self.speaker = SystemSpeaker() if speak else None

    def record_and_transcribe(
        self, seconds: float, auto_stop: bool = False, speech_threshold: float = 0.01,
        vad: str = "energy", vad_threshold: float = 0.5,
    ) -> str:
        try:
            if auto_stop:
                audio = self._record_until_silence(seconds, speech_threshold, vad, vad_threshold)
                if audio is None:
                    return ""
            else:
                audio = self.sd.rec(
                    int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                    channels=1, dtype="float32",
                )
                self.sd.wait()
        except (OSError, ValueError, self.sd.PortAudioError) as exc:
            raise RuntimeError(f"Microphone recording failed: {exc}") from exc
        return self.transcribe(audio)

    def transcribe(self, audio) -> str:
        if float((audio * audio).mean()) < SILENCE_RMS ** 2:
            return ""
        try:
            segments, _ = self.model.transcribe(
                audio.reshape(-1), beam_size=1,
                initial_prompt="The assistant is called Icewolf. The user is Dennis.",
            )
            return " ".join(segment.text.strip() for segment in segments).strip()
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError(f"Transcription failed: {exc}") from exc

    def _record_until_silence(self, seconds: float, threshold: float,
                              vad: str = "energy", vad_threshold: float = 0.5,
                              stream=None, stop_event=None, wait_for_speech=False,
                              end_silence_seconds: float = END_SILENCE_SECONDS,
                              fail_on_limit: bool = False):
        import numpy as np

        if vad not in ("energy", "silero"):
            raise ValueError(f"Unknown VAD: {vad}")
        if end_silence_seconds <= 0:
            raise ValueError("End-of-speech silence must be greater than zero.")
        if vad == "silero":
            from .vad import FRAME_SAMPLES as VAD_FRAME_SAMPLES, SileroDetector
            detector = SileroDetector()
            frame_size = VAD_FRAME_SAMPLES
        else:
            detector = None
            frame_size = FRAME_SAMPLES
        frames = []
        pre_roll = deque(maxlen=max(1, int(0.4 * SAMPLE_RATE / frame_size)))
        total_samples = 0
        silent_samples = 0
        heard_speech = False
        exceeded_limit = False
        limit = int(seconds * SAMPLE_RATE)
        source = (nullcontext(stream) if stream is not None else
                  self.sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32"))
        with source as stream:
            while total_samples < limit or (fail_on_limit and heard_speech):
                if stop_event is not None and stop_event.is_set():
                    return None
                remaining = limit - total_samples
                samples, overflowed = stream.read(
                    min(frame_size, remaining) if remaining > 0 else frame_size
                )
                if overflowed:
                    raise RuntimeError("Microphone input overflowed; try again or reduce system load.")
                if getattr(self, "level_callback", None) is not None:
                    self.level_callback(min(1.0, float(np.sqrt(np.mean(samples * samples))) * 5))
                if detector is not None:
                    frame = samples.reshape(-1)
                    if len(frame) < frame_size:
                        frame = np.pad(frame, (0, frame_size - len(frame)))
                    is_speech = detector.probability(frame) >= vad_threshold
                else:
                    is_speech = float(np.sqrt(np.mean(samples * samples))) >= threshold
                if wait_for_speech and not heard_speech:
                    pre_roll.append(samples)
                    if not is_speech:
                        continue
                    frames.extend(pre_roll)
                    total_samples = sum(len(frame) for frame in pre_roll)
                elif remaining > 0:
                    frames.append(samples)
                    total_samples += len(samples)
                else:
                    exceeded_limit = True
                if is_speech:
                    heard_speech = True
                    silent_samples = 0
                elif heard_speech:
                    silent_samples += len(samples)
                    if silent_samples >= end_silence_seconds * SAMPLE_RATE:
                        if exceeded_limit:
                            raise SpeechTooLong(
                                f"Recording exceeded {seconds:g} seconds; the request was not sent."
                            )
                        break
        return np.concatenate(frames) if heard_speech else None


class SystemSpeaker:
    def __init__(self):
        if sys.platform == "win32":
            self.engine = self._windows_voice()
            return
        try:
            import pyttsx3
        except ImportError as exc:
            raise RuntimeError(
                "Speech output requires pyttsx3. Install the packages in requirements.txt."
            ) from exc
        try:
            self.engine = pyttsx3.init()
        except (OSError, RuntimeError, ImportError) as exc:
            raise RuntimeError(f"Could not initialize the system speech engine: {exc}") from exc
        self._speech_errors = []
        self._completed = False
        self.engine.connect("error", self._on_error)
        self.engine.connect("finished-utterance", self._on_finished)

    def _windows_voice(self):
        try:
            import comtypes
            import comtypes.client
        except ImportError as exc:
            raise RuntimeError(
                "Windows speech output requires comtypes. Install the packages in requirements.txt."
            ) from exc
        self._com_error = comtypes.COMError
        try:
            return comtypes.client.CreateObject("SAPI.SpVoice")
        except (OSError, self._com_error) as exc:
            raise RuntimeError(f"Could not initialize the system speech engine: {exc}") from exc

    def _on_error(self, name, exception):
        self._speech_errors.append(exception)

    def _on_finished(self, name, completed):
        self._completed = completed

    def say(self, text: str) -> None:
        if sys.platform == "win32":
            try:
                # Synchronous speech with plain-text interpretation, not SAPI XML.
                self.engine.Speak(text, 16)
            except (OSError, self._com_error) as exc:
                raise RuntimeError(f"Speech output failed: {exc}") from exc
            return
        self._speech_errors.clear()
        self._completed = False
        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(f"Speech output failed: {exc}") from exc
        if self._speech_errors:
            raise RuntimeError(f"Speech output failed: {self._speech_errors[0]}")
        if not self._completed:
            raise RuntimeError("Speech output did not complete.")


class PiperSpeaker:
    def __init__(self, model_path: Path, length_scale: float = 1.0):
        if not 0.5 <= length_scale <= 2.0:
            raise ValueError("Piper length scale must be between 0.5 and 2.0.")
        model_path = model_path.expanduser().resolve()
        config_path = Path(f"{model_path}.json")
        if not model_path.is_file() or not config_path.is_file():
            raise ValueError(
                f"Piper needs a local model and matching .onnx.json file: {model_path}. "
                "See the Piper setup in README.md or use --tts system."
            )
        try:
            import numpy as np
            import sounddevice as sd
            from onnxruntime.capi import onnxruntime_pybind11_state as ort
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:
            raise RuntimeError(
                "Piper dependencies are missing. Install the packages in requirements.txt."
            ) from exc
        self.np = np
        self.sd = sd
        self.synthesis_config = SynthesisConfig(length_scale=length_scale)
        self._piper_errors = (
            OSError, ValueError, RuntimeError,
            ort.Fail, ort.InvalidArgument, ort.NoSuchFile, ort.RuntimeException,
            ort.InvalidGraph, ort.InvalidProtobuf, ort.NotImplemented,
        )
        try:
            self.voice = PiperVoice.load(model_path)
        except self._piper_errors as exc:
            raise RuntimeError(f"Could not load Piper voice {model_path}: {exc}") from exc

    def say(self, text: str, stop_event=None) -> None:
        try:
            chunks = []
            sample_rate = None
            for chunk in self.voice.synthesize(text, syn_config=self.synthesis_config):
                if stop_event is not None and stop_event.is_set():
                    return
                if chunk.sample_width != 2 or chunk.sample_channels != 1:
                    raise RuntimeError("Piper returned an unsupported audio format.")
                samples = self.np.frombuffer(chunk.audio_int16_bytes, dtype="<i2")
                if not samples.size:
                    continue
                if sample_rate is not None and chunk.sample_rate != sample_rate:
                    raise RuntimeError("Piper returned inconsistent sample rates.")
                sample_rate = chunk.sample_rate
                chunks.append(samples)
            if not chunks or sample_rate is None:
                raise RuntimeError("Piper produced no speech audio.")
            _play_audio(self.np, self.sd, chunks, sample_rate, "int16", stop_event)
        except (*self._piper_errors, self.sd.PortAudioError) as exc:
            raise RuntimeError(f"Piper speech output failed: {exc}") from exc


def _play_audio(np, sd, chunks, sample_rate, dtype, stop_event, level_callback=None):
    lead_in = np.zeros(int(sample_rate * 0.3), dtype=dtype)
    with sd.OutputStream(samplerate=sample_rate, channels=1, dtype=dtype) as stream:
        if stop_event is not None and stop_event.is_set():
            stream.abort()
            return
        if stream.write(lead_in.reshape(-1, 1)):
            raise RuntimeError("Audio output underflowed during the silent lead-in.")
        frame_size = max(1, sample_rate // 10)
        for samples in chunks:
            for start in range(0, len(samples), frame_size):
                if stop_event is not None and stop_event.is_set():
                    stream.abort()
                    return
                frame = samples[start:start + frame_size]
                if level_callback is not None:
                    level_callback(min(1.0, float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) * 5))
                if stream.write(frame.reshape(-1, 1)):
                    raise RuntimeError("Audio output underflowed; speech may be incomplete.")


class KokoroSpeaker:
    def __init__(self, model_path: Path, voices_path: Path, voice: str = "af_heart"):
        if not model_path.is_file() or not voices_path.is_file():
            raise ValueError("Kokoro model or voice file is missing; see README.md for setup.")
        try:
            import numpy as np
            import sounddevice as sd
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise RuntimeError("Kokoro dependencies are missing; install requirements-gui.txt.") from exc
        self.np, self.sd, self.voice = np, sd, voice
        self.level_callback = None
        try:
            self.engine = Kokoro(str(model_path), str(voices_path))
            if voice not in self.engine.get_voices():
                raise ValueError(f"Kokoro voice {voice} is unavailable.")
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError(f"Could not initialize Kokoro voice: {exc}") from exc

    def say(self, text: str, stop_event=None) -> None:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            samples, sample_rate = self.engine.create(text, voice=self.voice, lang="en-us")
            if stop_event is not None and stop_event.is_set():
                return
            if not len(samples) or sample_rate <= 0:
                raise RuntimeError("Kokoro produced no speech audio.")
            _play_audio(self.np, self.sd, [samples], sample_rate, "float32", stop_event, self.level_callback)
        except (OSError, ValueError, RuntimeError, self.sd.PortAudioError) as exc:
            raise RuntimeError(f"Kokoro speech output failed: {exc}") from exc
