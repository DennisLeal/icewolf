import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QLineEdit, QPlainTextEdit, QPushButton

from icewolf.gmail import MailItem
from icewolf.gmail_ui import GmailTools, create_pdf


class GmailUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ui = GmailTools(MagicMock())

    def tearDown(self):
        self.ui.close()
        self.app.processEvents()

    def test_unread_review_suppresses_marketing_but_shows_uncertain(self):
        first = MailItem("1", "t", "A", "Work", "", True)
        second = MailItem("2", "t", "B", "Sale", "", True)
        third = MailItem("3", "t", "C", "Unknown", "", True)
        self.ui.show_results([(first, "Jobs"), (second, "Marketing"), (third, "Other")], True)
        self.assertEqual(self.ui.list.count(), 2)
        self.assertIn("1 classified as marketing", self.ui.status.text())
        self.assertIn("All remain unread", self.ui.status.text())
        self.ui.show_skipped.setChecked(True)
        self.assertEqual(self.ui.list.count(), 3)

    def test_label_changes_require_confirmation_and_checked_items(self):
        mail = MailItem("1", "t", "A", "Work", "", True)
        self.ui.show_results([(mail, "Jobs")], False)
        self.ui.list.item(0).setCheckState(Qt.CheckState.Checked)
        self.ui.archive.setChecked(True)
        with patch.object(self.ui, "confirm_action", return_value=False), \
             patch.object(self.ui, "run_task") as task:
            self.ui.apply()
            task.assert_not_called()
        with patch.object(self.ui, "confirm_action", return_value=True), \
             patch.object(self.ui, "run_task") as task:
            self.ui.apply()
            task.assert_called_once()

    def test_send_requires_confirmation(self):
        def fill_and_send():
            dialog = QApplication.activeModalWidget()
            fields = dialog.findChildren(QLineEdit)
            fields[0].setText("person@example.com")
            fields[1].setText("Hello")
            dialog.findChild(QPlainTextEdit).setPlainText("Message")
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == "Review and send").click()
            dialog.reject()
        with patch.object(self.ui, "confirm_action", return_value=False), \
             patch.object(self.ui, "run_task") as task:
            QTimer.singleShot(0, fill_and_send)
            self.ui.compose(None)
            task.assert_not_called()

    def test_confirm_dialog_requires_yes_and_shows_plain_text(self):
        def approve():
            dialog = QApplication.activeModalWidget()
            self.assertEqual(dialog.findChild(QPlainTextEdit).toPlainText(), "Exact <email> text")
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Yes).click()
        QTimer.singleShot(0, approve)
        self.assertTrue(self.ui.confirm_action("Approval", "Exact <email> text"))

    def test_approved_send_schedules_exact_message(self):
        def fill_and_send():
            dialog = QApplication.activeModalWidget()
            fields = dialog.findChildren(QLineEdit)
            fields[0].setText("person@example.com")
            fields[1].setText("Hello")
            dialog.findChild(QPlainTextEdit).setPlainText("Exact message")
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == "Review and send").click()
        with patch.object(self.ui, "confirm_action", return_value=True) as confirm, \
             patch.object(self.ui, "run_task") as task, \
             patch("icewolf.gmail_ui.gmail.send_message") as send:
            QTimer.singleShot(0, fill_and_send)
            self.ui.compose(None)
            self.assertIn("Exact message", confirm.call_args.args[1])
            task.call_args.args[0]()
            send.assert_called_once_with("person@example.com", "Hello", "Exact message", None)

    def test_reply_draft_requires_confirmation_with_original_and_content(self):
        mail = MailItem("m", "t", "Sender", "Original subject", "", True,
                        "<id@example.com>", "sender@example.com")
        def fill_and_save():
            dialog = QApplication.activeModalWidget()
            dialog.findChild(QPlainTextEdit).setPlainText("Exact reply")
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == "Save draft").click()
            dialog.reject()
        with patch.object(self.ui, "confirm_action", return_value=False) as confirm, \
             patch.object(self.ui, "run_task") as task:
            QTimer.singleShot(0, fill_and_save)
            self.ui.compose(mail)
            self.assertIn("Original subject", confirm.call_args.args[1])
            self.assertIn("Exact reply", confirm.call_args.args[1])
            task.assert_not_called()

    def test_reply_and_modify_require_selected_message(self):
        with patch.object(self.ui, "show_error") as error, \
             patch.object(self.ui, "run_task") as task:
            self.ui.reply()
            self.ui.modify_selected()
            self.assertEqual(error.call_count, 2)
            task.assert_not_called()

    def test_message_change_requires_confirmation(self):
        mail = MailItem("m", "t", "Sender", "Subject", "", True)
        def choose():
            dialog = QApplication.activeModalWidget()
            dialog.findChild(QComboBox).setCurrentIndex(1)
            dialog.accept()
        with patch.object(self.ui, "confirm_action", return_value=False) as confirm, \
             patch.object(self.ui, "run_task") as task:
            QTimer.singleShot(0, choose)
            self.ui.modify_dialog(mail, [])
            self.assertIn("Mark read", confirm.call_args.args[1])
            task.assert_not_called()

    def test_bulk_read_preview_requires_approval_and_uses_only_unread(self):
        unread = MailItem("1", "t", "Sender", "Subject", "", True)
        read = MailItem("2", "t", "Other", "Read", "", False)
        with patch.object(self.ui, "confirm_action", return_value=False) as confirm, \
             patch.object(self.ui, "run_task") as task:
            self.ui.preview_bulk_read([unread, read])
            self.assertIn("1 unread inbox", confirm.call_args.args[1])
            task.assert_not_called()
        with patch.object(self.ui, "confirm_action", return_value=True), \
             patch.object(self.ui, "run_task") as task, \
             patch("icewolf.gmail_ui.gmail.modify_messages") as modify:
            self.ui.preview_bulk_read([unread, read])
            task.call_args.args[0]()
            self.assertEqual(modify.call_args.args[0], [unread])
            self.assertEqual(modify.call_args.args[1].remove, ("UNREAD",))

    def test_selected_message_context_and_ambiguous_request(self):
        mail = MailItem("1", "t", "Sender", "Subject", "", True)
        self.ui.show_all([mail])
        self.ui.list.setCurrentRow(0)
        self.assertEqual(self.ui.current_message.id, "1")
        with patch.object(self.ui, "compose") as compose:
            self.ui.start_request("reply", "Reply to that and say thanks")
            compose.assert_called_once_with(mail, request="Reply to that and say thanks")
        self.ui.current_message = None
        with patch.object(self.ui, "load_all") as load, patch.object(self.ui, "compose") as compose:
            self.ui.start_request("reply", "Reply to that")
            load.assert_called_once()
            compose.assert_not_called()

    def test_search_request_forwards_sender(self):
        with patch.object(self.ui, "run_task") as task, \
             patch("icewolf.gmail_ui.gmail.list_inbox", return_value=[]) as listing:
            self.ui.start_request("find", "Find email from bob@example.com")
            task.call_args.args[0]()
            listing.assert_called_once_with(all_mail=True, query="from:bob@example.com")

    def test_unspecified_change_cannot_apply_a_default(self):
        mail = MailItem("m", "t", "Sender", "Subject", "", True)
        def accept():
            QApplication.activeModalWidget().accept()
        with patch.object(self.ui, "show_error") as error, \
             patch.object(self.ui, "confirm_action") as confirm, \
             patch.object(self.ui, "run_task") as task:
            QTimer.singleShot(0, accept)
            self.ui.modify_dialog(mail, [], "Label this email")
            error.assert_called_once()
            confirm.assert_not_called()
            task.assert_not_called()

    def test_request_generates_draft_locally_with_explicit_address(self):
        self.ui.client._post.return_value = {"message": {"content": "Thank you for meeting."}}
        timer = QTimer()
        observed = []
        def check():
            dialog = QApplication.activeModalWidget()
            if dialog is None or self.ui.task is not None:
                return
            text = dialog.findChild(QPlainTextEdit).toPlainText()
            if not text:
                return
            fields = dialog.findChildren(QLineEdit)
            observed.extend([fields[0].text(), fields[1].text(), text])
            timer.stop()
            dialog.reject()
        timer.timeout.connect(check)
        timer.start(20)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: QApplication.activeModalWidget().reject())
        watchdog.start(3000)
        self.ui.compose(None, request="Email person@example.com about our meeting saying thank you")
        timer.stop()
        watchdog.stop()
        self.assertEqual(observed, ["person@example.com", "our meeting", "Thank you for meeting."])
        self.ui.client.check_model.assert_called_once()

    def test_create_pdf_contains_readable_text(self):
        from io import BytesIO
        from pypdf import PdfReader
        pdf = create_pdf("Popular salads\nGreek salad")
        self.assertTrue(pdf.startswith(b"%PDF-"))
        if self.app.platformName() != "offscreen":
            self.assertIn("Greek salad", PdfReader(BytesIO(pdf)).pages[0].extract_text())

    def test_pdf_request_prepares_and_approves_attachment(self):
        self.ui.client._post.return_value = {"message": {"content": "Popular salads\nGreek salad"}}
        request = "Create a PDF of popular salads and send it to me"
        timer = QTimer()
        def finish():
            dialog = QApplication.activeModalWidget()
            if dialog is None or self.ui.task is not None:
                return
            edits = dialog.findChildren(QPlainTextEdit)
            if len(edits) < 2 or not edits[1].toPlainText():
                return
            timer.stop()
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == "Review and send").click()
        timer.timeout.connect(finish)
        with patch("icewolf.gmail_ui.gmail.connected_address", return_value="me@example.com"), \
             patch.object(self.ui, "confirm_action", return_value=True) as approval, \
             patch("icewolf.gmail_ui.gmail.send_message") as send:
            timer.start(20)
            self.ui.compose(None, request)
            while self.ui.task is not None:
                self.app.processEvents()
            self.assertIn("Greek salad", approval.call_args.args[1])
            self.assertEqual(send.call_args.args[0], "me@example.com")
            self.assertTrue(send.call_args.args[4].startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
