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
        credentials.granted_scopes = None
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
        self.assertIn("Gmail tools", result.speech)
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
            "Read the first five emails in my inbox.",
            "Please read the first 5 emails in my inbox out loud.",
            "Read my latest five messages from my Gmail.",
            "Read out loud the first five emails in my inbox.",
            "Read me my first five emails.",
            "Hey Icewolf, read the first five emails in my inbox.",
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
            "Hey Icewolf check my email and delete it",
            "Don't send my email",
            "Don't check if I have any new emails",
            "Check my email from Alice please",
            "Check my work email",
            "Check my other email account",
            "Do I have any new emails from Alice?",
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

    def test_send_request_opens_tools_without_sending(self):
        client = MagicMock()
        speaker = MagicMock()
        worker = AssistantWorker(client, "text", "", "")
        requested = []
        worker.gmail_tools_requested.connect(requested.append)
        worker.respond("Send a Gmail message", speaker)
        client.reply.assert_not_called()
        self.assertEqual(requested, ["compose"])
        self.assertTrue(worker.stop_event.is_set())
        self.assertIn("review and approve", speaker.say.call_args.args[0])

    def test_natural_gmail_actions_speak_and_open_requested_tool(self):
        examples = {
            "Write an email for me": "compose",
            "Please organize my emails": "organize",
            "Review all my unread messages": "review",
            "Reply to this email": "reply",
            "Send a Gmail message": "compose",
        }
        for request, expected in examples.items():
            with self.subTest(request=request):
                client, speaker = MagicMock(), MagicMock()
                worker = AssistantWorker(client, "text", "")
                requested = []
                worker.gmail_tools_requested.connect(requested.append)
                worker.handle_transcript(request, speaker)
                self.assertEqual(requested, [expected])
                speaker.say.assert_called_once()
                client.reply.assert_not_called()

    def test_cancel_during_gmail_handoff_does_not_open_tools(self):
        worker = AssistantWorker(MagicMock(), "text", "")
        speaker = MagicMock()
        speaker.say.side_effect = lambda *args, **kwargs: worker.stop()
        requested = []
        worker.gmail_tools_requested.connect(requested.append)
        worker.respond("Write an email", speaker)
        self.assertEqual(requested, [])

    def test_unread_listing_paginates_without_modifying_messages(self):
        messages = MagicMock()
        messages.list.return_value.execute.side_effect = [
            {"messages": [{"id": "1"}], "nextPageToken": "next"},
            {"messages": [{"id": "2"}]},
        ]
        messages.get.return_value.execute.side_effect = [
            {"id": "1", "threadId": "t1", "labelIds": ["UNREAD"], "payload": {"headers": []}},
            {"id": "2", "threadId": "t2", "labelIds": ["UNREAD"], "payload": {"headers": []}},
        ]
        service = MagicMock()
        service.users.return_value.messages.return_value = messages
        from contextlib import nullcontext
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            result = gmail.list_inbox(unread_only=True)
        self.assertEqual([item.id for item in result], ["1", "2"])
        self.assertEqual(messages.list.call_args_list[0].kwargs["labelIds"], ["UNREAD"])
        self.assertEqual(messages.list.call_args_list[1].kwargs["pageToken"], "next")
        messages.modify.assert_not_called()
        messages.delete.assert_not_called()
        messages.trash.assert_not_called()

    def test_reply_message_preserves_thread_and_headers(self):
        import base64
        from email import policy
        from email.parser import BytesParser
        mail = gmail.MailItem("m", "thread", "A <a@example.com>", "Hello", "", True,
                              "<message@example.com>", "a@example.com", "<prior@example.com>")
        encoded = gmail._encoded_message("a@example.com", "Re: Hello", "Thank you.", mail)
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(encoded["raw"]))
        self.assertEqual(encoded["threadId"], "thread")
        self.assertEqual(message["In-Reply-To"], "<message@example.com>")
        self.assertIn("<prior@example.com>", message["References"])
        self.assertIn("<message@example.com>", message["References"])

    def test_send_and_draft_call_distinct_apis(self):
        from contextlib import nullcontext
        service = MagicMock()
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            gmail.save_draft("a@example.com", "Hi", "Hello")
            gmail.send_message("a@example.com", "Hi", "Hello")
        service.users.return_value.drafts.return_value.create.assert_called_once()
        service.users.return_value.messages.return_value.send.assert_called_once()
        service.users.return_value.messages.return_value.delete.assert_not_called()
        service.users.return_value.messages.return_value.trash.assert_not_called()

    def test_pdf_email_request_is_routed_without_sending(self):
        worker = AssistantWorker(MagicMock(), "text", "")
        requests = []
        worker.pdf_email_requested.connect(requests.append)
        request = "Create a PDF file with popular salads and send it over to me."
        worker.respond(request, MagicMock())
        self.assertEqual(requests, [request])
        self.assertTrue(worker.stop_event.is_set())

    def test_pdf_is_attached_to_message(self):
        import base64
        from email import policy
        from email.parser import BytesParser
        data = b"%PDF-1.4\nsample"
        result = gmail._encoded_message("a@example.com", "Salads", "Here you are", attachment=data)
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(result["raw"]))
        attachment = list(message.iter_attachments())[0]
        self.assertEqual(attachment.get_content_type(), "application/pdf")
        self.assertEqual(attachment.get_payload(decode=True), data)
        with self.assertRaises(ValueError):
            gmail._encoded_message("a@example.com", "Salads", "Here you are", attachment=b"invalid")

    def test_classification_rejects_missing_or_invented_entries(self):
        mail = gmail.MailItem("1", "t", "Sender", "Subject", "Preview", True)
        client = MagicMock()
        client.model = "local"
        client._post.return_value = {"message": {"content": '{"classifications": []}'}}
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            gmail.classify_messages(client, [mail])
        client._post.return_value = {"message": {"content": '{"classifications": [{"index": 0, "category": "Jobs"}]}'}}
        self.assertEqual(gmail.classify_messages(client, [mail]), [(mail, "Jobs")])

    def test_classification_keeps_important_mail_visible_and_skips_accepted_invite(self):
        items = [
            gmail.MailItem("1", "t", "LinkedIn", "New connection request", "Someone wants to connect", True),
            gmail.MailItem("2", "t", "LinkedIn", "Your invitation was accepted", "", True),
        ]
        client = MagicMock()
        client.model = "local"
        client._post.return_value = {"message": {"content": json.dumps({"classifications": [
            {"index": 0, "category": "Marketing"}, {"index": 1, "category": "Other"}
        ]})}}
        self.assertEqual([category for _, category in gmail.classify_messages(client, items)],
                         ["Other", "Marketing"])

    def test_organize_only_labels_and_optionally_archives(self):
        from contextlib import nullcontext
        mail = gmail.MailItem("1", "t", "Sender", "Subject", "", True)
        service = MagicMock()
        users = service.users.return_value
        users.labels.return_value.list.return_value.execute.return_value = {
            "labels": [{"name": "Icewolf - Jobs", "id": "label1"}]
        }
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            self.assertEqual(gmail.apply_labels([(mail, "Icewolf - Jobs")], True), 1)
        users.messages.return_value.modify.assert_called_once_with(
            userId="me", id="1", body={"addLabelIds": ["label1"], "removeLabelIds": ["INBOX"]}
        )
        users.messages.return_value.delete.assert_not_called()
        users.messages.return_value.trash.assert_not_called()

    def test_full_message_decodes_multipart_and_attachment_backed_text(self):
        import base64
        from contextlib import nullcontext
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.get.return_value.execute.return_value = {
            "id": "m", "threadId": "t", "payload": {
                "headers": [{"name": "Subject", "value": "=?utf-8?b?Q2Fmw6k=?="}],
                "parts": [{"mimeType": "text/plain", "body": {"attachmentId": "part"}}],
            },
        }
        messages.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode("Hello there".encode()).decode().rstrip("=")
        }
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            result = gmail.get_message("m")
        self.assertEqual(result.item.subject, "Café")
        self.assertEqual(result.body, "Hello there")
        messages.attachments.return_value.get.assert_called_once_with(
            userId="me", messageId="m", id="part"
        )
        self.assertEqual(gmail._message_body({
            "mimeType": "text/html", "body": {"data": "PHA-SGk8L3A-"}
        }), "Hi")
        with self.assertRaisesRegex(RuntimeError, "invalid encoded"):
            gmail._message_body({"mimeType": "text/plain", "body": {"data": "!!!"}})

    def test_modify_all_supported_changes_and_reject_trash(self):
        from contextlib import nullcontext
        service = MagicMock()
        users = service.users.return_value
        users.labels.return_value.list.return_value.execute.return_value = {
            "labels": [{"id": "CUSTOM", "type": "user", "name": "Custom"}]
        }
        mail = gmail.MailItem("m", "t", "Sender", "Subject", "", True)
        changes = [
            gmail.LabelChange(add=("CUSTOM",)),
            gmail.LabelChange(remove=("CUSTOM",)),
            gmail.LabelChange(remove=("UNREAD",)),
            gmail.LabelChange(add=("UNREAD",)),
            gmail.LabelChange(remove=("INBOX",)),
            gmail.LabelChange(add=("STARRED",)),
            gmail.LabelChange(remove=("STARRED",)),
        ]
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            for change in changes:
                self.assertEqual(gmail.modify_messages([mail], change), 1)
            with self.assertRaisesRegex(ValueError, "Only user labels"):
                gmail.modify_messages([mail], gmail.LabelChange(add=("TRASH",)))
        self.assertEqual(users.messages.return_value.modify.call_count, len(changes))
        users.messages.return_value.trash.assert_not_called()
        users.messages.return_value.delete.assert_not_called()

    def test_ambiguous_reply_and_modify_do_not_fall_through_to_model(self):
        for request, expected in (("Reply to that", "reply"), ("Mark it unread", "modify"),
                                  ("Remove label from that email", "modify")):
            with self.subTest(request=request):
                client = MagicMock()
                worker = AssistantWorker(client, "text", "")
                requested = []
                worker.gmail_tools_requested.connect(requested.append)
                worker.respond(request, MagicMock())
                self.assertEqual(requested, [expected])
                client.reply.assert_not_called()

    def test_search_request_is_forwarded_without_claiming_read(self):
        worker = AssistantWorker(MagicMock(), "text", "")
        requests, details = [], []
        worker.gmail_tools_requested.connect(requests.append)
        worker.gmail_request_details.connect(details.append)
        worker.respond("Read the email from Bob", MagicMock())
        self.assertEqual(requests, ["find"])
        self.assertEqual(details, ["Read the email from Bob"])
        worker.client.reply.assert_not_called()

    def test_bulk_read_request_is_forwarded_for_approval(self):
        worker = AssistantWorker(MagicMock(), "text", "")
        requests = []
        worker.gmail_tools_requested.connect(requests.append)
        worker.respond("Mark all my inbox messages as read", MagicMock())
        self.assertEqual(requests, ["bulk_read"])
        worker.client.reply.assert_not_called()

    def test_query_is_used_for_search_and_paginated(self):
        from contextlib import nullcontext
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        messages.list.return_value.execute.side_effect = [
            {"messages": [], "nextPageToken": "next"}, {"messages": []}
        ]
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            self.assertEqual(gmail.list_inbox(all_mail=True, query="from:bob"), [])
        self.assertEqual(messages.list.call_args_list[0].kwargs["q"], "from:bob")
        self.assertEqual(messages.list.call_args_list[1].kwargs["pageToken"], "next")

    def test_reply_must_keep_subject(self):
        mail = gmail.MailItem("m", "t", "Sender", "Subject", "", True,
                              "<message@example.com>", "a@example.com")
        with self.assertRaisesRegex(ValueError, "original subject"):
            gmail._encoded_message("a@example.com", "Different", "Hello", mail)

    def test_all_mail_empty_and_thread_retrieval(self):
        from contextlib import nullcontext
        service = MagicMock()
        users = service.users.return_value
        users.messages.return_value.list.return_value.execute.return_value = {}
        users.threads.return_value.get.return_value.execute.return_value = {
            "messages": [{"id": "m", "threadId": "t", "payload": {
                "mimeType": "text/plain", "body": {"data": "SGVsbG8"}
            }}]
        }
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            self.assertEqual(gmail.list_inbox(all_mail=True), [])
            result = gmail.get_thread("t")
        self.assertNotIn("labelIds", users.messages.return_value.list.call_args.kwargs)
        self.assertEqual(result[0].body, "Hello")

    def test_modify_reports_partial_failure_without_response_body(self):
        from contextlib import nullcontext
        from googleapiclient.errors import HttpError
        service = MagicMock()
        users = service.users.return_value
        users.labels.return_value.list.return_value.execute.return_value = {"labels": []}
        users.messages.return_value.modify.return_value.execute.side_effect = [
            {}, HttpError(SimpleNamespace(status=429, reason="rate limit"), b"private details")
        ]
        items = [gmail.MailItem(str(n), "t", "S", "Subject", "", True) for n in range(2)]
        with patch("icewolf.gmail.gmail_service", return_value=nullcontext(service)):
            with self.assertRaises(RuntimeError) as error:
                gmail.modify_messages(items, gmail.LabelChange(remove=("INBOX",)))
        self.assertIn("1 of 2", str(error.exception))
        self.assertIn("HTTP 429", str(error.exception))
        self.assertNotIn("private details", str(error.exception))

    def test_insufficient_scope_blocks_api_access(self):
        store = MagicMock()
        store.get_password.return_value = json.dumps({"token": "test"})
        credentials = MagicMock()
        credentials.has_scopes.return_value = False
        credentials.granted_scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        with patch("icewolf.gmail._credential_store", return_value=store), \
             patch("google.oauth2.credentials.Credentials.from_authorized_user_info",
                   return_value=credentials), \
             patch("googleapiclient.discovery.build") as build:
            with self.assertRaisesRegex(RuntimeError, "reconnect"):
                gmail.inbox_report()
        build.assert_not_called()

    def test_api_errors_are_actionable_and_do_not_leak_response(self):
        from googleapiclient.errors import HttpError
        store = MagicMock()
        store.get_password.return_value = json.dumps({"token": "test"})
        credentials = MagicMock()
        credentials.valid = True
        credentials.expired = False
        credentials.has_scopes.return_value = True
        credentials.granted_scopes = None
        service = MagicMock()
        messages = service.users.return_value.messages.return_value
        with patch("icewolf.gmail._credential_store", return_value=store), \
             patch("google.oauth2.credentials.Credentials.from_authorized_user_info",
                   return_value=credentials), \
             patch("google_auth_httplib2.AuthorizedHttp", return_value=MagicMock()), \
             patch("googleapiclient.discovery.build", return_value=service):
            for status, expected in ((400, "rejected"), (401, "reconnect"),
                                     (403, "denied"), (429, "rate limit")):
                messages.list.return_value.execute.side_effect = HttpError(
                    SimpleNamespace(status=status, reason="error"), b"private details"
                )
                with self.subTest(status=status), self.assertRaises(RuntimeError) as error:
                    gmail.inbox_report()
                self.assertIn(expected, str(error.exception))
                self.assertNotIn("private details", str(error.exception))

    def test_api_403_reasons_are_distinguished(self):
        from googleapiclient.errors import HttpError
        store = MagicMock()
        store.get_password.return_value = json.dumps({"token": "test"})
        credentials = MagicMock(valid=True, expired=False, granted_scopes=None)
        credentials.has_scopes.return_value = True
        service = MagicMock()
        execute = service.users.return_value.messages.return_value.list.return_value.execute
        with patch("icewolf.gmail._credential_store", return_value=store), \
             patch("google.oauth2.credentials.Credentials.from_authorized_user_info",
                   return_value=credentials), \
             patch("google_auth_httplib2.AuthorizedHttp", return_value=MagicMock()), \
             patch("googleapiclient.discovery.build", return_value=service):
            for reason, expected in (("SERVICE_DISABLED", "disabled"),
                                     ("insufficientPermissions", "permission is insufficient"),
                                     ("userRateLimitExceeded", "quota")):
                body = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
                execute.side_effect = HttpError(SimpleNamespace(status=403, reason="error"), body)
                with self.subTest(reason=reason), self.assertRaises(RuntimeError) as error:
                    gmail.inbox_report()
                self.assertIn(expected, str(error.exception))

    def test_rejects_non_desktop_oauth_clients(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as folder:
            file = Path(folder) / "client.json"
            for value in ({"type": "service_account"}, {"web": {}}, {"token": "test"}):
                file.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Desktop app"):
                    gmail.connect(str(file))


if __name__ == "__main__":
    unittest.main()
