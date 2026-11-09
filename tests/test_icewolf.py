import argparse
import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from icewolf.__main__ import main, parse_args, run
from icewolf.audio import KokoroSpeaker, PiperSpeaker, SpeechTooLong, SystemSpeaker, VoicePipeline, _play_audio
from icewolf.ollama import OllamaClient, SYSTEM_PROMPT
from icewolf.openai_local import LocalOpenAIClient


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self, size):
        return self.body[:size]


class OllamaTests(unittest.TestCase):
    def test_requests_stay_on_loopback_and_keep_conversation(self):
        requests = []

        class Connection:
            def __init__(self, host, port, timeout):
                self.host, self.port = host, port

            def request(self, method, path, body, headers):
                requests.append((self.host, self.port, path, json.loads(body)))

            def getresponse(self):
                return FakeResponse({"message": {"content": " Hello! "}})

            def close(self):
                pass

        with patch("icewolf.ollama.http.client.HTTPConnection", Connection):
            client = OllamaClient("llama3.2:3b")
            self.assertEqual(client.reply("Hi"), "Hello!")
            self.assertEqual(client.reply("Again"), "Hello!")
        self.assertTrue(all(item[:2] == ("127.0.0.1", 11434) for item in requests))
        self.assertEqual(requests[1][3]["messages"][-2]["content"], "Hello!")
        self.assertEqual(requests[1][3]["messages"][-1]["content"], "Again")

    def test_rejects_cloud_and_remote_model_names(self):
        for model in ("example.com/model", "model:cloud", "model name", ""):
            with self.subTest(model=model), self.assertRaises(ValueError):
                OllamaClient(model)

    def test_rejects_remote_model_metadata(self):
        client = OllamaClient("local")
        with patch.object(client, "_post", return_value={"remote_host": "example"}):
            with self.assertRaisesRegex(RuntimeError, "remote"):
                client.check_model()

    def test_empty_reply_does_not_change_history(self):
        client = OllamaClient("local")
        with patch.object(client, "_post", return_value={"message": {"content": ""}}):
            with self.assertRaises(RuntimeError):
                client.reply("Hi")
        self.assertEqual(client.messages, [{"role": "system", "content": SYSTEM_PROMPT}])

    def test_history_retains_system_and_complete_turns(self):
        client = OllamaClient("local")
        with patch.object(client, "_post", return_value={"message": {"content": "ok"}}):
            for i in range(20):
                client.reply(str(i))
        self.assertEqual(len(client.messages), 21)
        self.assertEqual(client.messages[0]["role"], "system")
        self.assertEqual([m["role"] for m in client.messages[1:]], ["user", "assistant"] * 10)

    def test_clear_history_keeps_system_prompt(self):
        client = OllamaClient("local")
        with patch.object(client, "_post", return_value={"message": {"content": "ok"}}):
            client.reply("Hi")
        client.clear_history()
        self.assertEqual(client.messages, [{"role": "system", "content": SYSTEM_PROMPT}])

    def test_selected_language_is_sent_without_changing_system_history(self):
        client = OllamaClient("local")
        with patch.object(client, "_post", return_value={"message": {"content": "ok"}}) as post:
            client.reply("Kumusta?", language="Tagalog")
        self.assertIn("Respond in Tagalog.", post.call_args.args[1]["messages"][0]["content"])
        self.assertEqual(client.messages[0]["content"], SYSTEM_PROMPT)
        with self.assertRaises(ValueError):
            client.reply("Hi", language="unsupported")


class VoiceTests(unittest.TestCase):
    def test_silero_conversation_keeps_speech_after_two_second_pause(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stream = MagicMock()
        stream.read.side_effect = lambda count: (np.ones((count, 1), dtype=np.float32), False)
        detector = MagicMock()
        detector.probability.side_effect = [0.9] + [0.0] * 63 + [0.9] + [0.0] * 94
        with patch("icewolf.vad.SileroDetector", return_value=detector):
            audio = pipeline._record_until_silence(
                15, 0.01, "silero", stream=stream, wait_for_speech=True,
                end_silence_seconds=3.0, fail_on_limit=True,
            )
        self.assertEqual(stream.read.call_count, 159)
        self.assertEqual(len(audio), 159 * 512)

    def test_conversation_limit_reports_incomplete_speech(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stream = MagicMock()
        stream.read.side_effect = (
            [(np.ones((1600, 1), dtype=np.float32), False)] * 25
            + [(np.zeros((1600, 1), dtype=np.float32), False)] * 30
        )
        with self.assertRaises(SpeechTooLong):
            pipeline._record_until_silence(
                2, 0.01, stream=stream, wait_for_speech=True,
                end_silence_seconds=3.0, fail_on_limit=True,
            )
        self.assertEqual(stream.read.call_count, 55)

    def test_conversation_can_stop_while_draining_overlong_speech(self):
        import threading
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stop = threading.Event()
        stream = MagicMock()
        def read(count):
            if stream.read.call_count == 25:
                stop.set()
            return np.ones((count, 1), dtype=np.float32), False
        stream.read.side_effect = read
        self.assertIsNone(pipeline._record_until_silence(
            2, 0.01, stream=stream, stop_event=stop, wait_for_speech=True,
            end_silence_seconds=3.0, fail_on_limit=True,
        ))
        self.assertEqual(stream.read.call_count, 25)

    def test_conversation_finishing_at_limit_is_not_rejected(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stream = MagicMock()
        stream.read.side_effect = (
            [(np.ones((1600, 1), dtype=np.float32), False)] * 10
            + [(np.zeros((1600, 1), dtype=np.float32), False)] * 30
        )
        audio = pipeline._record_until_silence(
            4, 0.01, stream=stream, wait_for_speech=True,
            end_silence_seconds=3.0, fail_on_limit=True,
        )
        self.assertEqual(len(audio), 64000)

    def test_conversation_accepts_speech_longer_than_old_limit(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stream = MagicMock()
        stream.read.side_effect = (
            [(np.ones((1600, 1), dtype=np.float32), False)] * 160
            + [(np.zeros((1600, 1), dtype=np.float32), False)] * 30
        )
        audio = pipeline._record_until_silence(
            30, 0.01, stream=stream, wait_for_speech=True,
            end_silence_seconds=3.0, fail_on_limit=True,
        )
        self.assertEqual(len(audio), 190 * 1600)

    def test_microphone_level_callback_tracks_recorded_audio(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        levels = []
        pipeline.level_callback = levels.append
        stream = SimpleNamespace(
            read=lambda count: (np.full((count, 1), 0.1, dtype=np.float32), False)
        )
        audio = pipeline._record_until_silence(0.1, 0.01, stream=stream)
        self.assertEqual(len(audio), 1600)
        self.assertAlmostEqual(levels[0], 0.5, places=5)

    def test_playback_level_callback_tracks_audio_frames(self):
        import numpy as np

        stream = MagicMock()
        stream.write.return_value = False
        output = MagicMock()
        output.__enter__.return_value = stream
        sounddevice = SimpleNamespace(OutputStream=MagicMock(return_value=output))
        levels = []
        _play_audio(np, sounddevice, [np.full(200, 0.1, dtype=np.float32)],
                    1000, "float32", None, levels.append)
        self.assertEqual(len(levels), 2)
        self.assertAlmostEqual(levels[0], 0.5, places=5)

    def test_missing_model_is_reported_without_downloading(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "model.bin"):
                VoicePipeline(Path(folder))

    def test_transcribes_recording(self):
        pipeline = object.__new__(VoicePipeline)
        audio = MagicMock()
        (audio * audio).mean.return_value = 0.01
        audio.reshape.return_value = "samples"
        pipeline.sd = SimpleNamespace(
            rec=lambda *args, **kwargs: audio, wait=lambda: None, PortAudioError=OSError
        )
        pipeline.model = SimpleNamespace(
            transcribe=lambda data, beam_size, initial_prompt: (
                iter([SimpleNamespace(text=" hello "), SimpleNamespace(text=" world")]), None
            )
        )
        self.assertEqual(pipeline.record_and_transcribe(1), "hello world")

    def test_silence_does_not_invoke_whisper(self):
        pipeline = object.__new__(VoicePipeline)
        audio = MagicMock()
        (audio * audio).mean.return_value = 0
        pipeline.sd = SimpleNamespace(
            rec=lambda *args, **kwargs: audio, wait=lambda: None, PortAudioError=OSError
        )
        pipeline.model = MagicMock()
        self.assertEqual(pipeline.record_and_transcribe(1), "")
        pipeline.model.transcribe.assert_not_called()

    def test_auto_stop_after_speech_and_pause(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        volumes = iter([0.0, 0.1] + [0.0] * 12 + [0.1])
        reads = []
        class Stream:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, count):
                reads.append(count)
                return np.full((count, 1), next(volumes), dtype=np.float32), False

        pipeline.sd = SimpleNamespace(InputStream=Stream, PortAudioError=OSError)
        pipeline.model = MagicMock()
        pipeline.model.transcribe.return_value = (iter([SimpleNamespace(text=" hello ")]), None)
        self.assertEqual(pipeline.record_and_transcribe(5, auto_stop=True), "hello")
        self.assertEqual(len(reads), 14)

    def test_auto_stop_no_speech_reaches_maximum_without_transcription(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        reads = []
        class Stream:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, count):
                reads.append(count)
                return np.zeros((count, 1), dtype=np.float32), False

        pipeline.sd = SimpleNamespace(InputStream=Stream, PortAudioError=OSError)
        pipeline.model = MagicMock()
        self.assertEqual(pipeline.record_and_transcribe(1.05, auto_stop=True), "")
        self.assertEqual(sum(reads), 16800)
        pipeline.model.transcribe.assert_not_called()

    def test_auto_stop_resets_pause_and_caps_continuous_speech(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        volumes = iter([0.1] + [0.0] * 11 + [0.1] * 8)
        reads = []
        class Stream:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, count):
                reads.append(count)
                return np.full((count, 1), next(volumes), dtype=np.float32), False

        pipeline.sd = SimpleNamespace(InputStream=Stream, PortAudioError=OSError)
        pipeline.model = MagicMock()
        pipeline.model.transcribe.return_value = (iter([SimpleNamespace(text="hello")]), None)
        self.assertEqual(pipeline.record_and_transcribe(2, auto_stop=True), "hello")
        self.assertEqual(sum(reads), 32000)

    def test_auto_stop_overflow_reports_error(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        class Stream:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, count):
                return np.zeros((count, 1), dtype=np.float32), True

        pipeline.sd = SimpleNamespace(InputStream=Stream, PortAudioError=OSError)
        with self.assertRaisesRegex(RuntimeError, "overflow"):
            pipeline.record_and_transcribe(1, auto_stop=True)

    def test_silero_recording_stops_after_speech(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        class Stream:
            def __init__(self, **kwargs):
                self.reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, count):
                self.reads += 1
                return np.full((count, 1), 0.1, dtype=np.float32), False

        detector = MagicMock()
        detector.probability.side_effect = [0.8] + [0.0] * 38
        pipeline.sd = SimpleNamespace(InputStream=Stream, PortAudioError=OSError)
        pipeline.model = MagicMock()
        pipeline.model.transcribe.return_value = (iter([SimpleNamespace(text="hello")]), None)
        with patch("icewolf.vad.SileroDetector", return_value=detector):
            self.assertEqual(pipeline.record_and_transcribe(5, auto_stop=True, vad="silero"), "hello")
        self.assertEqual(detector.probability.call_count, 39)

    def test_wake_recording_waits_through_silence_with_bounded_preroll(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stream = MagicMock()
        stream.read.side_effect = (
            [(np.zeros((1600, 1), dtype=np.float32), False)] * 40
            + [(np.full((1600, 1), 0.1, dtype=np.float32), False)]
            + [(np.zeros((1600, 1), dtype=np.float32), False)] * 12
        )
        audio = pipeline._record_until_silence(
            3, 0.01, stream=stream, wait_for_speech=True
        )
        self.assertEqual(stream.read.call_count, 53)
        self.assertEqual(len(audio), 1600 * 16)
        self.assertTrue(np.allclose(audio[3 * 1600:4 * 1600], 0.1))

    def test_silero_conversation_waits_past_utterance_limit_until_speech(self):
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stream = MagicMock()
        stream.read.side_effect = (
            [(np.zeros((512, 1), dtype=np.float32), False)] * 100
            + [(np.full((512, 1), 0.1, dtype=np.float32), False)]
            + [(np.zeros((512, 1), dtype=np.float32), False)] * 38
        )
        detector = MagicMock()
        detector.probability.side_effect = [0.0] * 100 + [0.9] + [0.0] * 38
        with patch("icewolf.vad.SileroDetector", return_value=detector):
            audio = pipeline._record_until_silence(
                2, 0.01, "silero", stream=stream, wait_for_speech=True
            )
        self.assertEqual(stream.read.call_count, 139)
        self.assertIsNotNone(audio)
        self.assertLessEqual(len(audio), 32000)

    def test_stop_interrupts_waiting_for_speech(self):
        import threading
        import numpy as np

        pipeline = object.__new__(VoicePipeline)
        stop = threading.Event()
        stream = MagicMock()
        def read(count):
            stop.set()
            return np.zeros((count, 1), dtype=np.float32), False
        stream.read.side_effect = read
        audio = pipeline._record_until_silence(
            15, 0.01, stream=stream, stop_event=stop, wait_for_speech=True
        )
        self.assertIsNone(audio)
        stream.read.assert_called_once()


class LocalOpenAITests(unittest.TestCase):
    def test_model_check_and_conversation(self):
        client = LocalOpenAIClient("publisher/model", port=1234)
        response = {"choices": [{"message": {"content": "Hello"}}]}
        with patch.object(client, "_request", return_value={"data": [{"id": "publisher/model"}]}) as request:
            client.check_model()
        request.assert_called_once_with("GET", "/v1/models")
        with patch.object(client, "_post", return_value=response) as post:
            self.assertEqual(client.reply("Hi"), "Hello")
        self.assertEqual(post.call_args.args[0], "/v1/chat/completions")
        self.assertEqual(client.messages[-1]["content"], "Hello")

    def test_missing_model_and_invalid_response_are_reported(self):
        client = LocalOpenAIClient("model")
        with patch.object(client, "_request", return_value={"data": []}):
            with self.assertRaisesRegex(RuntimeError, "not available"):
                client.check_model()
        with patch.object(client, "_post", return_value={"choices": []}):
            with self.assertRaisesRegex(RuntimeError, "invalid chat"):
                client.reply("Hi")
        self.assertEqual(client.messages, [{"role": "system", "content": SYSTEM_PROMPT}])

    def test_loopback_only(self):
        client = LocalOpenAIClient("model", port=1234)
        with patch("icewolf.ollama.http.client.HTTPConnection") as connection:
            connection.return_value.getresponse.return_value = FakeResponse({"data": []})
            client._request("GET", "/v1/models")
        connection.assert_called_once_with("127.0.0.1", 1234, timeout=180)


class SpeakerTests(unittest.TestCase):
    def setUp(self):
        self.voice = MagicMock()
        self.com_error = type("FakeCOMError", (Exception,), {})
        comtypes = types.ModuleType("comtypes")
        comtypes.COMError = self.com_error
        client = types.ModuleType("comtypes.client")
        client.CreateObject = MagicMock(return_value=self.voice)
        comtypes.client = client
        self.client = client
        self.modules = patch.dict("sys.modules", {"comtypes": comtypes, "comtypes.client": client})
        self.platform = patch("icewolf.audio.sys.platform", "win32")
        self.modules.start()
        self.platform.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.platform.stop)

    def test_windows_speaks_multiple_replies_synchronously_as_plain_text(self):
        speaker = SystemSpeaker()
        speaker.say("First reply.")
        speaker.say("Second <reply>.")
        self.assertEqual(self.voice.Speak.call_args_list, [
            unittest.mock.call("First reply.", 16),
            unittest.mock.call("Second <reply>.", 16),
        ])
        self.client.CreateObject.assert_called_once_with("SAPI.SpVoice")

    def test_windows_speech_errors_are_reported(self):
        speaker = SystemSpeaker()
        self.voice.Speak.side_effect = self.com_error("device failed")
        with self.assertRaisesRegex(RuntimeError, "Speech output failed.*device failed"):
            speaker.say("Hello")

    def test_windows_initialization_errors_are_reported(self):
        self.client.CreateObject.side_effect = self.com_error("no voice")
        with self.assertRaisesRegex(RuntimeError, "initialize.*no voice"):
            SystemSpeaker()

class KokoroTests(unittest.TestCase):
    def test_synthesis_uses_local_voice_and_playback(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            model, voices = Path(folder) / "model.onnx", Path(folder) / "voices.bin"
            model.touch()
            voices.touch()
            engine = MagicMock()
            engine.get_voices.return_value = ["af_heart"]
            engine.create.return_value = (np.ones(100, dtype=np.float32), 1000)
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stream.write.return_value = False
            with patch("kokoro_onnx.Kokoro", return_value=engine), \
                 patch("sounddevice.OutputStream", return_value=stream):
                KokoroSpeaker(model, voices).say("Hello.")
            engine.create.assert_called_once_with("Hello.", voice="af_heart", lang="en-us")
            self.assertEqual(stream.write.call_count, 2)

    def test_missing_kokoro_model_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "missing"):
                KokoroSpeaker(Path(folder) / "missing", Path(folder) / "voices")


class PiperTests(unittest.TestCase):
    def test_missing_model_fails_before_load(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "matching"):
                PiperSpeaker(Path(folder) / "missing.onnx")

    def test_multiple_chunks_and_replies_are_played(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "voice.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            chunk = SimpleNamespace(sample_width=2, sample_channels=1,
                                    sample_rate=22050, audio_int16_bytes=b"\x01\x00")
            voice = MagicMock()
            voice.synthesize.side_effect = lambda text, syn_config: iter([chunk, chunk])
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stream.write.return_value = False
            with patch("piper.PiperVoice.load", return_value=voice), \
                 patch("sounddevice.OutputStream", return_value=stream):
                speaker = PiperSpeaker(model)
                speaker.say("One")
                speaker.say("Two")
            self.assertEqual(stream.write.call_count, 6)
            import numpy as np
            writes = [call.args[0] for call in stream.write.call_args_list]
            self.assertEqual(len(writes[0]), 6615)
            self.assertTrue(np.all(writes[0] == 0))
            self.assertEqual([int(writes[i][0, 0]) for i in (1, 2, 4, 5)], [1] * 4)
            self.assertEqual(voice.synthesize.call_args_list,
                             [unittest.mock.call("One", syn_config=speaker.synthesis_config),
                              unittest.mock.call("Two", syn_config=speaker.synthesis_config)])
            self.assertEqual(speaker.synthesis_config.length_scale, 1.0)

    def test_piper_reports_output_underflow(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "voice.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            chunk = SimpleNamespace(sample_width=2, sample_channels=1,
                                    sample_rate=22050, audio_int16_bytes=b"\x01\x00")
            voice = MagicMock()
            voice.synthesize.return_value = iter([chunk])
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stream.write.side_effect = [False, True]
            with patch("piper.PiperVoice.load", return_value=voice), \
                 patch("sounddevice.OutputStream", return_value=stream):
                speaker = PiperSpeaker(model)
                with self.assertRaisesRegex(RuntimeError, "underflowed"):
                    speaker.say("Hello")

    def test_piper_stop_aborts_playback_without_writing_remaining_audio(self):
        import threading
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "voice.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            chunk = SimpleNamespace(sample_width=2, sample_channels=1,
                                    sample_rate=1000,
                                    audio_int16_bytes=np.ones(500, dtype="<i2").tobytes())
            voice = MagicMock()
            voice.synthesize.return_value = iter([chunk])
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stop = threading.Event()
            def write(samples):
                if stream.write.call_count == 2:
                    stop.set()
                return False
            stream.write.side_effect = write
            with patch("piper.PiperVoice.load", return_value=voice), \
                 patch("sounddevice.OutputStream", return_value=stream):
                PiperSpeaker(model).say("Hello", stop_event=stop)
            self.assertEqual(stream.write.call_count, 2)
            stream.abort.assert_called_once()

    def test_piper_length_scale_is_configurable_and_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "voice.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            with patch("piper.PiperVoice.load"):
                speaker = PiperSpeaker(model, length_scale=1.7)
            self.assertEqual(speaker.synthesis_config.length_scale, 1.7)
            for value in (0, 2.1, float("nan")):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    PiperSpeaker(model, length_scale=value)

    def test_synthesis_error_and_empty_audio_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "voice.onnx"
            model.touch()
            Path(f"{model}.json").touch()
            voice = MagicMock()
            with patch("piper.PiperVoice.load", return_value=voice):
                speaker = PiperSpeaker(model)
            voice.synthesize.side_effect = ValueError("invalid input")
            with self.assertRaisesRegex(RuntimeError, "Piper speech output failed.*invalid input"):
                speaker.say("Hello")
            voice.synthesize.side_effect = None
            voice.synthesize.return_value = iter([])
            with self.assertRaisesRegex(RuntimeError, "no speech audio"):
                speaker.say("Hello")


class CliTests(unittest.TestCase):
    def test_text_mode_does_not_require_whisper(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(parse_args(["--text", "--no-speech"]).text)

    def test_voice_mode_requires_model(self):
        with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args([])

    def test_recording_bounds(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for value in ("0", "31", "nan"):
                with self.subTest(value=value), self.assertRaises(SystemExit):
                    parse_args(["--text", "--seconds", value])

    def test_threshold_bounds(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for value in ("0", "1.1", "nan"):
                with self.subTest(value=value), self.assertRaises(SystemExit):
                    parse_args(["--text", "--speech-threshold", value])

    def test_silero_cli_options_are_validated(self):
        args = parse_args(["--text", "--auto-stop", "--vad", "silero", "--vad-threshold", "0.4"])
        self.assertEqual((args.vad, args.vad_threshold), ("silero", 0.4))
        with contextlib.redirect_stderr(io.StringIO()):
            for arguments in (
                ["--text", "--vad", "silero"],
                ["--text", "--vad-threshold", "nan"],
                ["--text", "--llm-port", "0"],
            ):
                with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                    parse_args(arguments)

    def test_piper_length_scale_bounds(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for value in ("0", "2.1", "nan"):
                with self.subTest(value=value), self.assertRaises(SystemExit):
                    parse_args(["--text", "--piper-length-scale", value])
        self.assertEqual(parse_args(["--text", "--piper-length-scale", "1.7"]).piper_length_scale, 1.7)

    def test_text_loop_outputs_reply_and_handles_eof(self):
        fake = SimpleNamespace(check_model=lambda: None, reply=lambda text: "Hello")
        with patch("icewolf.__main__.OllamaClient", return_value=fake), \
             patch("builtins.input", side_effect=["Hi", EOFError]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--text", "--no-speech"]), 0)
        self.assertIn("Icewolf: Hello", output.getvalue())

    def test_voice_loop_transcribes_and_speaks(self):
        fake_client = SimpleNamespace(check_model=lambda: None, reply=lambda text: "Hello")
        spoken = []
        fake_voice = SimpleNamespace(
            record_and_transcribe=lambda seconds: "Hi",
            speaker=SimpleNamespace(say=spoken.append),
        )
        args = argparse.Namespace(model="local", text=False, whisper_model="model",
                                  no_speech=False, seconds=2, auto_stop=False,
                                  tts="piper", piper_model="voice.onnx", piper_length_scale=1.4,
                                  backend="ollama", wake_model=None)
        with patch("icewolf.__main__.OllamaClient", return_value=fake_client), \
             patch("icewolf.__main__.VoicePipeline", return_value=fake_voice), \
             patch("icewolf.__main__.PiperSpeaker", return_value=fake_voice.speaker) as piper, \
             patch("builtins.input", side_effect=["", EOFError]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(EOFError):
                run(args)
        self.assertEqual(spoken, ["Hello"])
        piper.assert_called_once_with(Path("voice.onnx"), length_scale=1.4)

    def test_text_clear_and_system_voice_selection(self):
        client = MagicMock()
        client.reply.return_value = "Hello"
        speaker = MagicMock()
        with patch("icewolf.__main__.OllamaClient", return_value=client), \
             patch("icewolf.__main__.SystemSpeaker", return_value=speaker), \
             patch("icewolf.__main__.PiperSpeaker") as piper, \
             patch("builtins.input", side_effect=["Hi", "/clear", EOFError]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--text", "--tts", "system"]), 0)
        client.clear_history.assert_called_once()
        client.reply.assert_called_once_with("Hi")
        speaker.say.assert_called_once_with("Hello")
        piper.assert_not_called()

    def test_voice_loop_passes_auto_stop_options(self):
        fake_client = SimpleNamespace(check_model=lambda: None, reply=lambda text: "Hello")
        transcribe = MagicMock(return_value="Hi")
        fake_voice = SimpleNamespace(record_and_transcribe=transcribe, speaker=None)
        args = argparse.Namespace(model="local", text=False, whisper_model="model",
                                  no_speech=True, seconds=15, auto_stop=True,
                                  speech_threshold=0.005, vad="energy", backend="ollama",
                                  wake_model=None)
        with patch("icewolf.__main__.OllamaClient", return_value=fake_client), \
             patch("icewolf.__main__.VoicePipeline", return_value=fake_voice), \
             patch("builtins.input", side_effect=["", EOFError]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(EOFError):
                run(args)
        transcribe.assert_called_once_with(15, auto_stop=True, speech_threshold=0.005)


if __name__ == "__main__":
    unittest.main()
