import contextlib
import io
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from icewolf.__main__ import main, parse_args
from icewolf.wake import WAKE_FRAME_SAMPLES, IcewolfPhraseListener, WakeWordListener, is_icewolf_phrase


class WakeTests(unittest.TestCase):
    def test_wait_uses_pcm_frames_and_detects_threshold(self):
        listener = object.__new__(WakeWordListener)
        listener.model = MagicMock()
        listener.model.predict.side_effect = [{"key": 0.1}, {"key": 0.7}]
        listener.model_key = "key"
        listener.threshold = 0.5
        listener._errors = (ValueError,)
        stream = MagicMock()
        stream.read.return_value = (np.full((WAKE_FRAME_SAMPLES, 1), 0.5, dtype=np.float32), False)
        listener.wait(stream)
        listener.model.reset.assert_called_once()
        self.assertEqual(stream.read.call_count, 2)
        samples = listener.model.predict.call_args.args[0]
        self.assertEqual(samples.dtype, np.int16)
        self.assertEqual(samples.shape, (WAKE_FRAME_SAMPLES,))
        self.assertEqual(samples[0], 16383)

    def test_overflow_is_reported(self):
        listener = object.__new__(WakeWordListener)
        listener.model = MagicMock()
        stream = MagicMock()
        stream.read.return_value = (np.zeros((WAKE_FRAME_SAMPLES, 1)), True)
        with self.assertRaisesRegex(RuntimeError, "overflow"):
            listener.wait(stream)

    def test_missing_model_is_reported(self):
        with self.assertRaisesRegex(ValueError, "Missing wake-word model files"):
            WakeWordListener(Path("not-a-model.onnx"))

    def test_invalid_cli_combinations(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for args in (["--text", "--wake-model", "x.onnx"],
                         ["--text", "--wake-threshold", "nan"]):
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    parse_args(args)

    def test_hey_icewolf_is_opt_in_default_model(self):
        args = parse_args(["--wake", "--whisper-model", "whisper"])
        self.assertEqual(args.wake_model, "icewolf")
        self.assertIsNone(parse_args(["--text"]).wake_model)

    def test_icewolf_phrase_requires_exact_utterance(self):
        for value in ("Hey Icewolf.", "Hey, Ice Wolf!"):
            self.assertTrue(is_icewolf_phrase(value))
        for value in ("hey jarvis", "hello icewolf", "hey icewolf delete files", "hey wolf"):
            self.assertFalse(is_icewolf_phrase(value))

    def test_icewolf_detector_only_activates_on_matching_transcript(self):
        voice = MagicMock()
        audio = MagicMock()
        voice._record_until_silence.return_value = audio
        voice.model.transcribe.side_effect = [
            (iter([SimpleNamespace(text="Hey Jarvis")]), None),
            (iter([SimpleNamespace(text="Hey Ice Wolf")]), None),
        ]
        stream = MagicMock()
        self.assertTrue(IcewolfPhraseListener(voice).wait(stream))
        self.assertEqual(voice.model.transcribe.call_count, 2)
        self.assertEqual(stream.stop.call_count, 2)
        stream.start.assert_called_once()

    def test_desktop_wake_can_accept_only_approved_inline_request(self):
        voice = MagicMock()
        voice._record_until_silence.return_value = MagicMock()
        voice.model.transcribe.side_effect = [
            (iter([SimpleNamespace(text="Hey Icewolf, delete my email")]), None),
            (iter([SimpleNamespace(text="Hey Icewolf, check my email")]), None),
        ]
        matcher = lambda text: text == "check my email"
        listener = IcewolfPhraseListener(voice, inline_request_matcher=matcher,
                                         end_silence_seconds=4.5)
        stream = MagicMock()
        self.assertTrue(listener.wait(stream))
        self.assertEqual(listener.inline_request, "check my email")
        self.assertEqual(voice.model.transcribe.call_count, 2)
        self.assertEqual(voice._record_until_silence.call_args.kwargs["end_silence_seconds"], 4.5)
        self.assertTrue(voice._record_until_silence.call_args.kwargs["fail_on_limit"])

    def test_icewolf_stop_event_prevents_listening(self):
        stop = threading.Event()
        stop.set()
        voice = MagicMock()
        self.assertFalse(IcewolfPhraseListener(voice).wait(MagicMock(), stop))
        voice._record_until_silence.assert_not_called()

    def test_stop_event_ends_wait(self):
        listener = object.__new__(WakeWordListener)
        listener.model = MagicMock()
        stop = threading.Event()
        stop.set()
        stream = MagicMock()
        self.assertFalse(listener.wait(stream, stop))
        stream.read.assert_not_called()

    def test_wake_handoff_shares_microphone_and_closes_before_transcription(self):
        args = parse_args(["--wake-model", "x.onnx", "--whisper-model", "whisper",
                           "--seconds", "8", "--no-speech"])
        stream = MagicMock()
        stream.__enter__.return_value = stream
        active = []
        stream.__enter__.side_effect = lambda: (active.append(True) or stream)
        def close_stream(*args):
            active.pop()
            return False
        stream.__exit__.side_effect = close_stream
        voice = MagicMock()
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream), PortAudioError=OSError)
        audio = object()
        voice._record_until_silence.return_value = audio
        def transcribe(value):
            self.assertFalse(active)
            self.assertIs(value, audio)
            return "Hello"
        voice.transcribe.side_effect = transcribe
        wake = MagicMock()
        wake.wait.side_effect = [None, KeyboardInterrupt]
        client = MagicMock()
        client.reply.return_value = "Hi"
        with patch("icewolf.__main__.parse_args", return_value=args), \
             patch("icewolf.__main__.VoicePipeline", return_value=voice), \
             patch("icewolf.__main__.OllamaClient", return_value=client), \
             patch("icewolf.wake.WakeWordListener", return_value=wake), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([]), 0)
        voice._record_until_silence.assert_called_once_with(8, 0.01, "silero", 0.5, stream)
        client.reply.assert_called_once_with("Hello")


if __name__ == "__main__":
    unittest.main()
