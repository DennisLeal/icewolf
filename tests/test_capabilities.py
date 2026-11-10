import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from icewolf.capabilities import CAPABILITIES, is_capabilities_request
from icewolf.desktop import AssistantWorker
from icewolf.gmail_conversation import GmailSession


class CapabilitiesTests(unittest.TestCase):
    def test_natural_identity_requests(self):
        for request in ("Who are you?", "Hey Icewolf, what can you do?",
                        "Could you explain your capabilities please?",
                        "Tell me about yourself", "What are you capable of?",
                        "Who is Icewolf?", "Tell me thoroughly what you can do"):
            with self.subTest(request=request):
                self.assertTrue(is_capabilities_request(request))
        for request in ("What can you do about my email?", "Search YouTube",
                        "Who are you referring to?", "Do not tell me what you can do"):
            with self.subTest(request=request):
                self.assertFalse(is_capabilities_request(request))

    def test_worker_speaks_full_description_without_model(self):
        client, speaker = MagicMock(), MagicMock()
        worker = AssistantWorker(client, "text", "", "Who are you?")
        messages, errors = [], []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        worker.failed.connect(errors.append)
        client.check_model.side_effect = RuntimeError("offline")
        with patch("icewolf.desktop.create_speaker", return_value=speaker):
            worker.run()
        client.check_model.assert_not_called()
        client.reply.assert_not_called()
        self.assertEqual(errors, [])
        self.assertEqual(messages[-1][1], "\n\n".join(CAPABILITIES))
        self.assertEqual([call.args[0] for call in speaker.say.call_args_list], list(CAPABILITIES))
        self.assertIn("cannot currently record", messages[-1][1])

    def test_voice_and_cancellation(self):
        worker = AssistantWorker(MagicMock(), "wake", "")
        speaker = MagicMock()
        speaker.say.side_effect = lambda *args, **kwargs: worker.stop()
        worker.handle_transcript("What can you do?", speaker)
        speaker.say.assert_called_once()

    def test_inline_wake_request_reaches_spoken_response(self):
        worker = AssistantWorker(MagicMock(), "wake", "whisper")
        speaker, voice, stream, wake = (MagicMock() for _ in range(4))
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream), PortAudioError=OSError)
        wake.wait.return_value = True
        wake.inline_request = "What can you do?"
        def finish_after_last_section(*args, **kwargs):
            if speaker.say.call_count == len(CAPABILITIES):
                worker.stop()
        speaker.say.side_effect = finish_after_last_section
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.IcewolfPhraseListener", return_value=wake) as listener:
            worker.run()
        self.assertTrue(listener.call_args.kwargs["inline_request_matcher"]("What can you do?"))
        self.assertEqual([call.args[0] for call in speaker.say.call_args_list], list(CAPABILITIES))
        worker.client.reply.assert_not_called()

    def test_pending_trash_confirmation_takes_precedence(self):
        session = GmailSession(pending_trash=[MagicMock()], pending_since=1)
        worker = AssistantWorker(MagicMock(), "text", "", gmail_session=session)
        speaker = MagicMock()
        worker.respond("Who are you?", speaker)
        self.assertNotEqual(speaker.say.call_args.args[0], CAPABILITIES[0])


if __name__ == "__main__":
    unittest.main()
