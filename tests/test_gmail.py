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
        self.assertIn("Ask me to read or manage", result.speech)
        messages.list.assert_called_once_with(userId="me", labelIds=["INBOX"], maxResults=5)
        messages.get.assert_called_once()
        http.close.assert_called_once()


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
