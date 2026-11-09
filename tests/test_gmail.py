import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from icewolf import gmail
from icewolf.desktop import AssistantWorker


class GmailTests(unittest.TestCase):
    def test_inbox_requires_authorization(self):
        store = MagicMock()
        store.get_password.return_value = None
        with patch("icewolf.gmail._credential_store", return_value=store):
            with self.assertRaisesRegex(RuntimeError, "not connected"):
                gmail.inbox_report()

    def test_report_lists_message_metadata_without_modifying_mail(self):
        store = MagicMock()
        store.get_password.return_value = json.dumps({"token": "test"})
        credentials = MagicMock()
        credentials.expired = False
        credentials.valid = True
        credentials.has_scopes.return_value = True
        messages = MagicMock()
        messages.list.return_value.execute.return_value = {"messages": [{"id": "123"}]}
        messages.get.return_value.execute.return_value = {
            "payload": {"headers": [
                {"name": "From", "value": "Sender"},
                {"name": "Subject", "value": "Meeting"},
            ]},
            "snippet": "You&#39;re invited. Please reply.",
        }
        service = MagicMock()
        service.users.return_value.messages.return_value = messages
        http = MagicMock()
        with patch("icewolf.gmail._credential_store", return_value=store), \
             patch("google.oauth2.credentials.Credentials.from_authorized_user_info",
                   return_value=credentials), \
             patch("google_auth_httplib2.AuthorizedHttp", return_value=http), \
             patch("googleapiclient.discovery.build", return_value=service):
            result = gmail.inbox_report()
        self.assertIn("Sender", result.display)
        self.assertIn("Meeting", result.display)
        self.assertIn("You're invited.", result.display)
        self.assertNotIn("invited", result.speech)
        self.assertNotIn("&#39;", result.speech)
        self.assertIn("Number 1 is from Sender, about Meeting.", result.speech)
        self.assertIn("Would you like to prepare a reply", result.speech)
        self.assertIn("can't send or change messages yet", result.speech)
        messages.list.assert_called_once_with(userId="me", labelIds=["INBOX"], maxResults=5)
        messages.get.assert_called_once()
        http.close.assert_called_once()

    def test_voice_gmail_request_uses_real_inbox_not_llm(self):
        client = MagicMock()
        speaker = MagicMock()
        worker = AssistantWorker(client, "text", "", "")
        report = gmail.InboxReport("Full inbox report", "Short spoken report")
        with patch("icewolf.desktop.gmail.inbox_report", return_value=report):
            worker.respond("Check my Gmail.", speaker)
        client.reply.assert_not_called()
        speaker.say.assert_called_once_with("Short spoken report", stop_event=worker.stop_event)

    def test_natural_inbox_requests_are_routed_to_gmail(self):
        requests = (
            "Can you check my email?",
            "Please check my emails.",
            "Could you check my Gmail please?",
            "Icewolf, can you check my inbox?",
            "Check my e-mail.",
            "Read my emails.",
            "What's in my inbox?",
            "What's going on in my Gmail?",
            "Report my Gmail",
            "Check my Gmail.",
            "Give me an email report.",
            "Hey icewolf check my email",
            "Hey, Icewolf, check my email.",
            "Hey Icewolf, can you check my email for me please?",
            "Check my email for me",
            "Could you check my latest emails right now?",
            "Please check if I have any new emails.",
            "Do I have any new email?",
            "Are there any new messages in my inbox?",
            "What new emails do I have?",
            "Check my mail",
            "Can you check my connected email account?",
        )
        report = gmail.InboxReport("Full inbox report", "Short spoken report")
        for request in requests:
            with self.subTest(request=request):
                client, speaker = MagicMock(), MagicMock()
                worker = AssistantWorker(client, "text", "")
                with patch("icewolf.desktop.gmail.inbox_report", return_value=report) as inbox:
                    worker.handle_transcript(request, speaker)
                inbox.assert_called_once_with()
                client.reply.assert_not_called()
                speaker.say.assert_called_once_with(report.speech, stop_event=worker.stop_event)

    def test_specific_or_negated_mail_requests_do_not_fetch_or_claim_success(self):
        requests = (
            "Don't check my email",
            "Check my email from Alice",
            "How many unread emails do I have?",
            "Delete my email",
            "Can you send my email?",
            "Hey Icewolf check my email and delete it",
            "Don't check if I have any new emails",
            "Check my email from Alice please",
            "Check my work email",
            "Check my other email account",
            "Do I have any new emails from Alice?",
            "Check my inbox and send a reply",
            "Read the email from Bob",
            "Can you check my Outlook email?",
        )
        for request in requests:
            with self.subTest(request=request):
                client, speaker = MagicMock(), MagicMock()
                worker = AssistantWorker(client, "text", "")
                with patch("icewolf.desktop.gmail.inbox_report") as inbox:
                    worker.respond(request, speaker)
                inbox.assert_not_called()
                client.reply.assert_not_called()
                self.assertIn("not available", speaker.say.call_args.args[0])

    def test_inbox_request_in_active_voice_conversation(self):
        client, speaker, voice, stream, wake = (MagicMock() for _ in range(5))
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream),
                                   PortAudioError=OSError)
        voice.transcribe.return_value = "Can you check my email?"
        wake.wait.return_value = True
        worker = AssistantWorker(client, "wake", "whisper")
        report = gmail.InboxReport("Full inbox report", "Short spoken report")
        messages, errors = [], []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        worker.failed.connect(errors.append)
        def capture(*args, **kwargs):
            if voice._record_until_silence.call_count == 2:
                worker.stop()
                return None
            return "audio"
        voice._record_until_silence.side_effect = capture
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.IcewolfPhraseListener", return_value=wake), \
             patch("icewolf.desktop.gmail.inbox_report", return_value=report) as inbox:
            worker.run()
        self.assertEqual(errors, [])
        wake.wait.assert_called_once()
        inbox.assert_called_once()
        client.reply.assert_not_called()
        self.assertIn(("Icewolf", report.display), messages)
        self.assertEqual(speaker.say.call_args_list[-1].args[0], report.speech)
        self.assertEqual(voice._record_until_silence.call_count, 2)

    def test_wake_phrase_and_inbox_request_together_use_gmail(self):
        client, speaker, voice, stream = (MagicMock() for _ in range(4))
        stream.__enter__.return_value = stream
        voice.sd = SimpleNamespace(InputStream=MagicMock(return_value=stream),
                                   PortAudioError=OSError)
        voice.model.transcribe.return_value = (
            iter([SimpleNamespace(text="Hey Icewolf, check my email.")]), None
        )
        worker = AssistantWorker(client, "wake", "whisper")
        report = gmail.InboxReport("Full inbox report", "Short spoken report")
        messages, errors = [], []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        worker.failed.connect(errors.append)
        def capture(*args, **kwargs):
            if voice._record_until_silence.call_count == 2:
                worker.stop()
                return None
            return MagicMock()
        voice._record_until_silence.side_effect = capture
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.VoicePipeline", return_value=voice), \
             patch("icewolf.desktop.gmail.inbox_report", return_value=report) as inbox:
            worker.run()
        self.assertEqual(errors, [])
        inbox.assert_called_once_with()
        client.reply.assert_not_called()
        self.assertIn(("You", "check my email."), messages)
        speaker.say.assert_called_once_with(report.speech, stop_event=worker.stop_event)
        self.assertEqual(voice._record_until_silence.call_count, 2)

    def test_inbox_error_is_reported_without_llm_fallback(self):
        client, speaker = MagicMock(), MagicMock()
        worker = AssistantWorker(client, "text", "", "Can you check my email?")
        errors = []
        worker.failed.connect(errors.append)
        with patch("icewolf.desktop.create_speaker", return_value=speaker), \
             patch("icewolf.desktop.gmail.inbox_report",
                   side_effect=RuntimeError("Gmail authorization unavailable")):
            worker.run()
        self.assertEqual(errors, ["RuntimeError: Gmail authorization unavailable"])
        client.reply.assert_not_called()
        speaker.say.assert_not_called()

    def test_button_and_voice_requests_use_same_spoken_report(self):
        report = gmail.InboxReport("Full inbox report", "Short spoken report")
        speaker = MagicMock()
        worker = AssistantWorker(None, "gmail", "")
        messages = []
        worker.message.connect(lambda role, text: messages.append((role, text)))
        with patch("icewolf.desktop.gmail.inbox_report", return_value=report), \
             patch("icewolf.desktop.create_speaker", return_value=speaker):
            worker.run()
        self.assertEqual(messages, [("Icewolf", report.display)])
        speaker.say.assert_called_once_with(report.speech, stop_event=worker.stop_event)

    def test_long_report_speech_is_bounded_and_excludes_addresses(self):
        self.assertEqual(gmail._clean("You&#39;re welcome", 100), "You're welcome")
        self.assertLessEqual(len(gmail._clean("x" * 1000, 70)), 70)

    def test_unsupported_gmail_request_does_not_claim_success(self):
        client = MagicMock()
        speaker = MagicMock()
        worker = AssistantWorker(client, "text", "", "")
        worker.respond("Send a Gmail message", speaker)
        client.reply.assert_not_called()
        self.assertIn("not available", speaker.say.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
